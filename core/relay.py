"""把调用方的决策请求转给上游入口，响应翻译回 SystemOne 形状。

调用方统一说 SystemOne；网关按入口登记的协议类型翻译后再发给上游。
自定义协议入口不做翻译，原样透传。
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from . import hooks
from . import protocol
from .entries import Entry, KIND_DECISIONS, KIND_SYSTEMONE

#: 网关自己产生的错误（状态码, 说明）
ERROR_GATEWAY_UNAVAILABLE = (502, "上游不可达")
ERROR_GATEWAY_TIMEOUT = (504, "上游超时")

#: 重试的退避间隔（秒）
BACKOFF_SECONDS = (0.4, 1.2)


def upstream_format(entry: Entry) -> str:
    """入口的协议类型 → 实际请求格式。custom 不翻译，按 SystemOne 原样发。"""
    if entry.kind == KIND_DECISIONS:
        return protocol.API_FORMAT_DECISIONS
    if entry.kind == KIND_SYSTEMONE:
        return protocol.API_FORMAT_SYSTEMONE
    return protocol.API_FORMAT_SYSTEMONE


def build_headers(entry: Entry, headers: dict[str, str]) -> dict[str, str]:
    """透传客户端头，换成入口自己的鉴权。"""
    out = hooks.strip_hop_by_hop(dict(headers))
    for key in list(out):
        if key.lower() in hooks.DROP_REQUEST_HEADERS or key.lower() == "authorization":
            out.pop(key, None)
    if entry.api_key:
        out["Authorization"] = f"Bearer {entry.api_key}"
    for key, value in entry.headers.items():
        out[key] = value
    return out


def parse_internal_body(body: bytes) -> tuple[dict, list[str]]:
    """解析调用方发来的内部请求体，返回 (请求, 问题清单)。

    内部形状：{"model": ..., "state": ..., "questions": {...}}
    """
    if not body:
        return {}, ["请求体为空"]
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return {}, [f"请求体不是合法 JSON：{exc}"]
    if not isinstance(data, dict):
        return {}, ["请求体必须是对象"]
    problems = protocol.validate_request(data.get("state"), data.get("questions") or {})
    return data, problems


async def forward(
    entry: Entry,
    method: str,
    headers: dict[str, str],
    body: bytes,
    client: httpx.AsyncClient | None = None,
    retries: int = 1,
) -> tuple[int, dict[str, str], bytes]:
    """转发一次决策请求，返回 (状态码, 响应头, 响应体)。

    响应统一是 SystemOne 形状，调用方不必关心上游讲的是哪种协议。
    """
    url = entry.url
    if not url:
        return 400, {}, b'{"error":"entry has no base_url"}'

    internal, problems = parse_internal_body(body)
    if problems:
        return 400, {}, json.dumps(
            {"status": "invalid_request", "retryable": False, "problems": problems},
            ensure_ascii=False,
        ).encode("utf-8")

    ctx = {
        "method": method,
        "path": url,
        "headers": dict(headers),
        "body": body,
        "internal": internal,
    }
    patched = await hooks.before_forward(entry, ctx)
    if patched:
        body = patched.get("body", body)
        internal = patched.get("internal", internal)
        if internal is not ctx["internal"]:
            ctx["internal"] = internal

    model = str(internal.get("model") or entry.model or "").strip()
    state = internal.get("state")
    questions = internal.get("questions") or {}
    api_format = upstream_format(entry)
    payload = protocol.build_payload(model, state, questions, api_format)
    upstream_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    request_headers = build_headers(entry, headers)
    request_headers["Content-Type"] = "application/json"

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=entry.timeout)
    status = 0
    resp_headers: dict[str, str] = {}
    resp_body = b""
    try:
        for attempt in range(max(0, retries) + 1):
            try:
                response = await client.request(
                    method.upper(),
                    url,
                    content=upstream_body or None,
                    headers=request_headers,
                )
            except httpx.TimeoutException:
                if attempt < retries:
                    await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                    continue
                return ERROR_GATEWAY_TIMEOUT[0], {}, b'{"error":"upstream timeout"}'
            except httpx.HTTPError as exc:
                if attempt < retries:
                    await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                    continue
                return ERROR_GATEWAY_UNAVAILABLE[0], {}, (
                    '{"error":"upstream unreachable: %s"}' % str(exc).replace('"', "'")
                ).encode("utf-8")

            status = response.status_code
            resp_headers = hooks.strip_hop_by_hop(dict(response.headers))
            resp_body = response.content
            if status in protocol.RETRYABLE_STATUS and attempt < retries:
                await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            break
    finally:
        if own_client:
            await client.aclose()

    resp_headers.pop("content-encoding", None)
    resp_headers.pop("content-length", None)

    if status == 200 and api_format == protocol.API_FORMAT_DECISIONS:
        resp_body = _translate_response(resp_body, questions)

    ctx = {
        "status": status,
        "headers": dict(resp_headers),
        "body": resp_body,
    }
    patched = await hooks.after_response(entry, ctx)
    if patched:
        return (
            int(patched.get("status", ctx["status"])),
            patched.get("headers", ctx["headers"]),
            patched.get("body", ctx["body"]),
        )
    return status, resp_headers, resp_body


def _translate_response(body: bytes, questions: dict) -> bytes:
    """Decisions 响应 → SystemOne 形状。"""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return body
    if not isinstance(data, dict):
        return body
    translated = protocol.to_systemone_response(data)
    if not protocol.valid_answers(translated, questions, require_all=False):
        return body
    return json.dumps(translated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
