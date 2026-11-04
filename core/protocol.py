"""Jev 协议层：SystemOne ⇄ OpenAI Decisions 翻译、请求预检、错误映射。

网关内部统一用 SystemOne 形状跟调用方说话；只有在发给上游时才按入口的协议
类型翻译，收到响应再翻译回来。调用方（各插件）的判定逻辑因此不必关心上游
讲的是哪种协议。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

API_FORMAT_SYSTEMONE = "systemone"
API_FORMAT_DECISIONS = "decisions"
API_FORMATS = (API_FORMAT_SYSTEMONE, API_FORMAT_DECISIONS)

ENDPOINT_PATHS = {
    API_FORMAT_SYSTEMONE: "/v1/systemone",
    API_FORMAT_DECISIONS: "/v1/decisions",
}

MAX_QUESTIONS = 8
MAX_STATE_CHARS = 1_000_000
MAX_INSTRUCTIONS_CHARS = 1_800
MAX_CRITERIA_CHARS = 2_000
MAX_QUESTION_NAME_CHARS = 64
MIN_CHOICE_OPTIONS = 2
MAX_CHOICE_OPTIONS = 20
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10

#: 问题名是标识符：字母、数字和下划线
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# json.dumps 最坏情况下的转义膨胀：控制字符会展开成 \uXXXX（6 字符）
_MAX_ESCAPE_EXPANSION = 6


# ── 错误映射 ─────────────────────────────────────────────────────────
RETRYABLE_STATUS = {409, 429, 500, 502, 503, 529}

_STATUS_BY_HTTP = {
    401: "unauthorized",
    402: "insufficient_credits",
    403: "forbidden",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "upstream_error",
    502: "upstream_error",
    503: "overloaded",
    529: "overloaded",
}


def error_status(http_status: int) -> str:
    """把 HTTP 状态码映射成可读状态（未列出的按通用错误处理）。"""
    return _STATUS_BY_HTTP.get(int(http_status), "error")


def parse_error(payload) -> tuple[str, str]:
    """解析错误包，返回 (类型, 消息)；兼容 error 为字符串或 message 在顶层。"""
    if not isinstance(payload, dict):
        return "", ""
    error = payload.get("error")
    if isinstance(error, str):
        return "", error.strip()
    if isinstance(error, dict):
        return str(error.get("type") or ""), str(error.get("message") or "")
    for key in ("message", "detail", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return "", value.strip()
    return "", ""


# ── 请求预检 ─────────────────────────────────────────────────────────
def serialized_length(value) -> int:
    """按文档的口径估算序列化长度（文档以序列化后的字符数设限）。"""
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return 0


def _raw_len(value) -> int:
    """粗估 value 序列化前的字符数（只用于判断「会不会超限」）。"""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(len(str(k)) + _raw_len(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_raw_len(v) for v in value)
    return len(str(value))


def _may_exceed(value, limit: int) -> bool:
    """保守判断：value 序列化后是否有可能超过上限。

    文档按序列化后的字符数设限，而序列化最多把一个字符膨胀成 6 个
    （控制字符的转义序列）。raw 长度小到膨胀 6 倍都够不着上限时，
    就不必真去 dumps 一遍算精确长度——预检每次要序列化 5 份数据，
    这是纯浪费。判断只会「跳过必然通过」的检查，不会放过真正的超限。
    """
    return _MAX_ESCAPE_EXPANSION * _raw_len(value) + 16 > limit


def validate_request(state, questions) -> list[str]:
    """本地预检请求体，返回问题清单（空列表＝本地校验通过）。

    规则照搬文档的校验器；提前拦下必然 422 的请求，省一次往返与一次额度预留。
    """
    problems: list[str] = []
    if not isinstance(questions, dict) or not questions:
        return ["questions 必须是非空对象"]

    if len(questions) > MAX_QUESTIONS:
        problems.append(f"一次请求最多 {MAX_QUESTIONS} 个问题（当前 {len(questions)} 个）")

    if _may_exceed(state, MAX_STATE_CHARS):
        state_len = serialized_length(state)
        if state_len > MAX_STATE_CHARS:
            problems.append(f"state 序列化后 {state_len} 字符，超过上限 {MAX_STATE_CHARS}")

    for name, question in questions.items():
        if (
            not isinstance(name, str)
            or not _NAME_RE.match(name)
            or len(name) > MAX_QUESTION_NAME_CHARS
        ):
            problems.append(
                f"问题名 {name!r} 非法：只允许字母、数字和下划线，最长 {MAX_QUESTION_NAME_CHARS} 字符"
            )
            continue
        if not isinstance(question, dict):
            problems.append(f"问题 {name!r} 必须是对象")
            continue

        qtype = question.get("type")
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            problems.append(f"问题 {name!r} 缺少 instructions")
        elif len(instructions) > MAX_INSTRUCTIONS_CHARS:
            problems.append(
                f"问题 {name!r} 的 instructions {len(instructions)} 字符，"
                f"超过上限 {MAX_INSTRUCTIONS_CHARS}"
            )

        criteria = question.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or not criteria:
                problems.append(f"问题 {name!r} 是 choice，criteria 必须是非空对象")
            elif not MIN_CHOICE_OPTIONS <= len(criteria) <= MAX_CHOICE_OPTIONS:
                problems.append(
                    f"问题 {name!r} 的 choice 选项数为 {len(criteria)}，"
                    f"应为 {MIN_CHOICE_OPTIONS}-{MAX_CHOICE_OPTIONS}"
                )
        elif qtype == "score":
            if not isinstance(criteria, list) or not criteria:
                problems.append(f"问题 {name!r} 是 score，criteria 必须是非空数组")
            elif not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
                problems.append(
                    f"问题 {name!r} 的 score 级数为 {len(criteria)}，"
                    f"应为 {MIN_SCORE_LEVELS}-{MAX_SCORE_LEVELS}"
                )
        elif qtype == "noul":
            if criteria is not None and not isinstance(criteria, dict):
                problems.append(f"问题 {name!r} 是 noul，criteria 只能是对象或省略")
        elif qtype == "box":
            pass  # box 只用 instructions，不接受 criteria
        else:
            problems.append(f"问题 {name!r} 的 type {qtype!r} 不受支持")

        if criteria is not None and _may_exceed(criteria, MAX_CRITERIA_CHARS):
            criteria_len = serialized_length(criteria)
            if criteria_len > MAX_CRITERIA_CHARS:
                problems.append(
                    f"问题 {name!r} 的 criteria 序列化后 {criteria_len} 字符，"
                    f"超过上限 {MAX_CRITERIA_CHARS}"
                )
    return problems


# ── 协议翻译 ─────────────────────────────────────────────────────────
def _decisions_input(state) -> str:
    """SystemOne 的 state → Decisions 的 input（只收字符串，对象就序列化成 JSON）。"""
    if isinstance(state, str):
        return state
    try:
        return json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(state)


def _decisions_question(name: str, question: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """SystemOne 的问题定义 → Decisions 的问题定义（noul→predicate，criteria→choices/levels）。"""
    qtype = question.get("type")
    if qtype not in ("choice", "noul", "score"):
        # box 等 SystemOne 独有类型，Decisions 没有对应物
        return None
    out: Dict[str, Any] = {
        "name": name,
        "type": "predicate" if qtype == "noul" else qtype,
        "instructions": question.get("instructions", ""),
    }
    if qtype == "choice":
        criteria = question.get("criteria") or {}
        out["choices"] = [
            {"value": key, "description": value} for key, value in criteria.items()
        ]
    elif qtype == "score":
        criteria = question.get("criteria") or []
        out["levels"] = [{"label": str(item)} for item in criteria]
    return out


def build_payload(
    model: str,
    state: Any,
    questions: Dict[str, Any],
    api_format: str = API_FORMAT_SYSTEMONE,
) -> Dict[str, Any]:
    """按目标协议拼请求体。"""
    if api_format == API_FORMAT_DECISIONS:
        return {
            "model": model,
            "input": _decisions_input(state),
            "questions": [
                item
                for item in (
                    _decisions_question(name, question)
                    for name, question in questions.items()
                )
                if item is not None
            ],
        }
    return {"model": model, "state": state, "questions": questions}


def to_systemone_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """把 Decisions 的响应翻译回 SystemOne 的形状（答案映射 + 概率映射 + noul）。"""
    if not isinstance(data, dict):
        return data
    answers = data.get("answers")
    if not isinstance(answers, list):
        return data
    converted: Dict[str, Any] = {}
    for item in answers:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        atype = item.get("type")
        if atype == "predicate":
            converted[name] = {"type": "noul", "noul": item.get("probability")}
        elif atype == "choice":
            probabilities: Dict[str, float] = {}
            for entry in item.get("probabilities") or []:
                if isinstance(entry, dict) and "value" in entry:
                    probabilities[str(entry["value"])] = entry.get("probability")
            converted[name] = {
                "type": "choice",
                "choice": item.get("choice"),
                "probabilities": probabilities,
                "confidence": item.get("confidence"),
            }
        elif atype == "score":
            converted[name] = {
                "type": "score",
                "score": item.get("score"),
                "confidence": item.get("confidence"),
            }
        # refusal：Decisions 允许「这题拒答」，SystemOne 形状里没有对应物，
        # 直接跳过（这题当作没答）。
    result = dict(data)
    result["answers"] = converted
    return result


def valid_answers(data, questions, require_all: bool = True) -> bool:
    """检查响应里的答案是否覆盖了请求里的每个问题。"""
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        return False
    if require_all:
        return all(name in answers for name in questions)
    return bool(answers)
