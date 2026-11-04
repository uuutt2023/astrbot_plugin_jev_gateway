"""把网关收到的请求转发到上游入口，响应原样带回。"""

from __future__ import annotations

import httpx

from . import hooks
from .entries import Entry

#: 网关自己产生的错误（状态码, 说明）
ERROR_GATEWAY_UNAVAILABLE = (502, "上游不可达")
ERROR_GATEWAY_TIMEOUT = (504, "上游超时")


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


async def forward(
    entry: Entry,
    method: str,
    headers: dict[str, str],
    body: bytes,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """转发一次请求，返回 (状态码, 响应头, 响应体)。

    上游的响应不做改写，客户端拿到的东西和直连上游一致。
    """
    url = entry.url
    if not url:
        return 400, {}, b'{"error":"entry has no base_url"}'

    ctx = {"method": method, "path": url, "headers": dict(headers), "body": body}
    patched = await hooks.before_forward(entry, ctx)
    if patched:
        body = patched.get("body", body)
        headers = patched.get("headers", headers)

    request_headers = build_headers(entry, headers)

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=entry.timeout)
    try:
        response = await client.request(
            method.upper(),
            url,
            content=body or None,
            headers=request_headers,
        )
    except httpx.TimeoutException:
        return ERROR_GATEWAY_TIMEOUT[0], {}, (
            '{"error":"upstream timeout"}'
        ).encode("utf-8")
    except httpx.HTTPError as exc:
        return ERROR_GATEWAY_UNAVAILABLE[0], {}, (
            '{"error":"upstream unreachable: %s"}' % str(exc).replace('"', "'")
        ).encode("utf-8")
    finally:
        if own_client:
            await client.aclose()

    resp_headers = hooks.strip_hop_by_hop(dict(response.headers))
    resp_headers.pop("content-encoding", None)
    resp_headers.pop("content-length", None)

    ctx = {
        "status": response.status_code,
        "headers": dict(resp_headers),
        "body": response.content,
    }
    patched = await hooks.after_response(entry, ctx)
    if patched:
        return (
            int(patched.get("status", ctx["status"])),
            patched.get("headers", ctx["headers"]),
            patched.get("body", ctx["body"]),
        )
    return response.status_code, resp_headers, response.content
