"""余额追踪：记下每次请求返回的余额，也支持自定义查询地址。

两种来源：
- 随响应回来的：官方 Jev 在响应头 `X-Tokens-Remaining`，第三方代理在响应体
  `usage.credits_remaining_usd`。
- 自定义查询：入口上配了 `balance_url` 就定时/按需去查，`balance_field` 指明
  从返回 JSON 里取哪个字段（支持 `a.b.c` 这种点号路径）。
"""

from __future__ import annotations

import time
from typing import Any

BALANCE_HEADERS = ("x-tokens-remaining", "x-credits-remaining")
BODY_FIELD = "credits_remaining_usd"


def _dig(data: Any, path: str) -> Any:
    """按点号路径取值：`a.b.c`。取不到返回 None。"""
    current = data
    for part in str(path or "").split("."):
        if not part:
            return None
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def extract_from_response(headers: dict[str, str], body: bytes) -> tuple[str | None, float | None]:
    """从一次上游响应里抠出余额。

    返回 (单位, 数值)：单位是 "tokens" 或 "usd"，都没有则 (None, None)。
    """
    for key in BALANCE_HEADERS:
        for name, value in (headers or {}).items():
            if name.lower() != key:
                continue
            try:
                return "tokens", float(str(value).strip())
            except (TypeError, ValueError):
                continue
    try:
        import json

        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, None
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None, None
    value = usage.get(BODY_FIELD)
    if value is None:
        return None, None
    try:
        return "usd", float(value)
    except (TypeError, ValueError):
        return None, None


class BalanceTracker:
    """记录每个入口的余额。"""

    def __init__(self):
        self._balances: dict[str, dict[str, Any]] = {}

    def record(self, protocol: str, unit: str | None, value: float | None,
               source: str = "response") -> None:
        if unit is None or value is None:
            return
        self._balances[protocol] = {
            "unit": unit,
            "value": value,
            "source": source,
            "updated_at": time.time(),
        }

    def record_response(self, protocol: str, headers: dict[str, str], body: bytes) -> None:
        unit, value = extract_from_response(headers, body)
        if unit is not None:
            self.record(protocol, unit, value)

    def get(self, protocol: str) -> dict[str, Any] | None:
        return self._balances.get(protocol)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._balances)

    def clear(self) -> None:
        self._balances.clear()


async def query_custom(entry, client=None) -> tuple[str | None, float | None, str]:
    """按入口配的 balance_url 查询余额。

    返回 (单位, 数值, 错误说明)；查不到时数值是 None。
    """
    url = (entry.balance_url or "").strip()
    if not url:
        return None, None, "未配置自定义余额地址"
    field = (entry.balance_field or "").strip()
    try:
        import httpx

        own_client = client is None
        client = client or httpx.AsyncClient(timeout=entry.timeout)
        try:
            headers = {}
            if entry.api_key:
                headers["Authorization"] = f"Bearer {entry.api_key}"
            response = await client.get(url, headers=headers)
        finally:
            if own_client:
                await client.aclose()
        if response.status_code >= 400:
            return None, None, f"HTTP {response.status_code}"
        try:
            data = response.json()
        except ValueError:
            return None, None, "返回不是 JSON"
    except Exception as exc:  # noqa: BLE001 - 查询失败不该影响主流程
        return None, None, str(exc)
    if not field:
        return None, None, "未指定余额字段"
    value = _dig(data, field)
    if value is None:
        return None, None, f"返回里没有字段 {field}"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, None, f"字段 {field} 不是数字"
    unit = "usd" if any(k in field.lower() for k in ("usd", "credit", "balance", "amount")) else "raw"
    return unit, number, ""
