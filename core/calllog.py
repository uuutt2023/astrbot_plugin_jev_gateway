"""调用日志：记下每次调用用了什么提示词、回了什么结果。

网关是所有 Jev 调用的必经之路，所以提示词与结果都在这里留一份，
方便在 WebUI 里翻「谁问的、问了什么、模型怎么答的」。

保留时间可配，默认 7 天；到期自动清理，同时按条数兜底，防止内存涨爆。
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any

#: 默认保留 7 天
DEFAULT_RETENTION_DAYS = 7.0
#: 最多留多少条（按条数兜底，防止高频调用把内存吃满）
DEFAULT_MAX_ENTRIES = 500
#: 日志里 state 最多留这么多字符，超出截断
MAX_STATE_CHARS = 2000
#: 响应体最多留这么多字符
MAX_RESPONSE_CHARS = 4000


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _prompt_text(questions: Any) -> str:
    """把问题集合压成一段人能读的提示词。"""
    if not isinstance(questions, dict):
        return ""
    parts = []
    for name, question in questions.items():
        if not isinstance(question, dict):
            continue
        instructions = str(question.get("instructions") or "").strip()
        parts.append(f"{name}: {instructions}" if instructions else str(name))
    return "\n".join(parts)


def _result_text(response: Any) -> str:
    """从响应里抽出结果摘要。"""
    if not isinstance(response, dict):
        return ""
    answers = response.get("answers")
    if isinstance(answers, dict):
        parts = []
        for name, answer in answers.items():
            if isinstance(answer, dict):
                value = answer.get("noul")
                if value is None:
                    value = answer.get("choice")
                if value is None:
                    value = answer.get("level")
                if value is None:
                    value = answer.get("probability")
                parts.append(f"{name}={value}")
            else:
                parts.append(f"{name}={answer}")
        if parts:
            return ", ".join(parts)
    return ""


class CallLog:
    """带过期清理的调用日志。"""

    def __init__(self, retention_seconds: float | None = None,
                 max_entries: int | None = None):
        self.retention_seconds = (
            DEFAULT_RETENTION_DAYS * 86400 if retention_seconds is None else retention_seconds
        )
        self.max_entries = DEFAULT_MAX_ENTRIES if max_entries is None else max_entries
        self._items: deque[dict] = deque(maxlen=max(1, int(self.max_entries)))
        self._seq = 0

    def configure(self, retention_seconds: float | None = None,
                  max_entries: int | None = None) -> None:
        """改保留时长或条数上限。"""
        if retention_seconds is not None:
            self.retention_seconds = max(0.0, float(retention_seconds))
        if max_entries is not None:
            limit = max(1, int(max_entries))
            if limit != self.max_entries:
                self._items = deque(self._items, maxlen=limit)
                self.max_entries = limit

    # ── 记录 ────────────────────────────────────────────────────
    def record(self, *, client: str = "", protocol: str = "", entry_id: str = "",
               state: str = "", questions: Any = None, response: Any = None,
               status: int = 0, elapsed_ms: float = 0.0,
               cached: bool = False) -> dict:
        """记一条调用，返回这条记录。"""
        self._seq += 1
        state_text, truncated = _truncate(str(state or ""), MAX_STATE_CHARS)
        response_text = ""
        if isinstance(response, (bytes, bytearray)):
            response_text = response.decode("utf-8", errors="replace")
            response_text, resp_truncated = _truncate(response_text, MAX_RESPONSE_CHARS)
            truncated = truncated or resp_truncated
            parsed = _parse_json(bytes(response))
        else:
            parsed = response
        item = {
            "id": self._seq,
            "at": time.time(),
            "client": client or "",
            "protocol": protocol or "",
            "entry": entry_id or "",
            "status": int(status or 0),
            "elapsed_ms": round(float(elapsed_ms or 0.0), 1),
            "cached": bool(cached),
            "prompt": _prompt_text(questions),
            "questions": questions if isinstance(questions, dict) else {},
            "state": state_text,
            "truncated": truncated,
            "result": _result_text(parsed),
            "response": parsed if parsed is not None else response_text,
        }
        self._items.append(item)
        self.prune()
        return item

    # ── 读取 ────────────────────────────────────────────────────
    def snapshot(self, limit: int = 100, client: str = "") -> list[dict]:
        """最近的调用，最新的在前。可按客户端名过滤。"""
        rows = list(self._items)
        if client:
            rows = [row for row in rows if row.get("client") == client]
        rows.reverse()
        return rows[: max(1, int(limit))]

    def prune(self) -> int:
        """清掉过期的记录，返回清掉多少条。"""
        if self.retention_seconds <= 0:
            return 0
        deadline = time.time() - self.retention_seconds
        kept = [row for row in self._items if row.get("at", 0) >= deadline]
        removed = len(self._items) - len(kept)
        if removed:
            self._items.clear()
            self._items.extend(kept)
        return removed

    def stats(self) -> dict:
        """给 WebUI 顶部看的一行摘要。"""
        rows = list(self._items)
        clients = {row.get("client") for row in rows if row.get("client")}
        return {
            "count": len(rows),
            "clients": sorted(clients),
            "retention_days": round(self.retention_seconds / 86400, 3),
            "max_entries": self.max_entries,
        }

    def clear(self) -> None:
        self._items.clear()
