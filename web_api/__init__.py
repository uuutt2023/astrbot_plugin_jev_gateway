"""WebUI 后端 API：入口配置、连通性测试、余额查询。

通过 AstrBot 的 register_web_api 机制注册（/api/plug/...）。
优先使用新版 astrbot.api.web（4.27+）；旧版回退 quart request/jsonify。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from astrbot.api import logger

from ..core import balancer as balancer_mod
from ..core import topology as topology_mod

try:
    from astrbot.api.web import error_response, json_response, request
    HAS_WEB_API = True
except ImportError:  # 兼容旧版 AstrBot（无 astrbot.api.web）
    from quart import jsonify, request  # type: ignore

    HAS_WEB_API = False


def _ok(data: Any = None, message: str = "") -> Any:
    if HAS_WEB_API:
        return json_response({"status": "ok", "message": message, "data": data})
    return jsonify({"status": "ok", "message": message, "data": data})


def _err(message: str, status_code: int = 400) -> Any:
    if HAS_WEB_API:
        return error_response(message, status_code=status_code)
    resp = jsonify({"status": "error", "message": message, "data": {}})
    resp.status_code = status_code
    return resp


def _query_param(name: str, default: str = "") -> str:
    """读查询参数，兼容新版 astrbot.api.web 与 quart 两种形态。"""
    try:
        for attr in ("query", "args", "query_params"):
            holder = getattr(request, attr, None)
            if not holder:
                continue
            value = holder.get(name)
            if value is not None:
                return str(value)
    except Exception:  # noqa: BLE001 - 取不到就用默认值
        pass
    return default


async def _get_json() -> Dict:
    """读取请求体 JSON，兼容新版 astrbot.api.web 与 quart 两种形态。"""
    if HAS_WEB_API:
        data = await request.json(default=None)
    else:
        try:
            data = await request.json
        except Exception:
            data = None
    return data if isinstance(data, dict) else {}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _entry_payload(entry) -> Dict[str, Any]:
    return {
        # 稳定标识：拓扑图里的节点靠它对上号
        "id": entry.id,
        "protocol": entry.protocol,
        "kind": entry.kind,
        "base_url": entry.base_url,
        # 明文 Key 不出后端：前端留空表示不改
        "model": entry.model,
        "endpoint_path": entry.endpoint_path,
        "timeout": entry.timeout,
        "priority": entry.priority,
        "weight": entry.weight,
        "balance_url": entry.balance_url,
        "balance_field": entry.balance_field,
        "url": entry.url,
        "key_masked": entry.masked_key(),
    }


class GatewayAPI:
    """网关的入口配置、测试与余额查询。"""

    def __init__(self, plugin):
        self._plugin = plugin

    # ── 入口配置 ────────────────────────────────────────────────
    async def get_entries(self):
        registry = self._plugin._build_registry()
        items: List[Dict[str, Any]] = []
        for protocol, group in registry.items():
            for index, entry in enumerate(group):
                payload = _entry_payload(entry)
                payload["primary"] = index == 0
                items.append(payload)
        items_cfg = self._plugin._items()
        return _ok(
            {
                "entries": items,
                "running": bool(self._plugin.server.port),
                "endpoint_base": self._plugin.endpoint_base,
                "settings": {
                    "host": items_cfg.get("host", "127.0.0.1"),
                    "port": items_cfg.get("port", 8770),
                    "advertised_url": items_cfg.get("advertised_url", ""),
                    "access_token_set": bool(items_cfg.get("access_token")),
                    "lb_strategy": items_cfg.get("lb_strategy", "round_robin"),
                    "log_retention_days": items_cfg.get("log_retention_days", 7.0),
                    "log_max_entries": items_cfg.get("log_max_entries", 500),
                },
            }
        )

    async def get_calls(self):
        """最近的调用记录：谁调的、提示词是什么、结果是什么。"""
        try:
            limit = max(1, min(500, int(_query_param("limit", "50"))))
        except (TypeError, ValueError):
            limit = 50
        client = _query_param("client", "").strip()
        server = self._plugin.server
        return _ok(
            {
                "calls": server.calllog.snapshot(limit=limit, client=client),
                "stats": server.calllog.stats(),
            }
        )

    async def get_topology(self):
        """拓扑图数据：接入对象 → 网关 → API 入口。"""
        server = self._plugin.server
        items_cfg = self._plugin._items()
        graph = topology_mod.build_graph(
            server.registry,
            server.clients,
            server.balancer.snapshot(),
            server.balances.snapshot(),
            gateway={
                "host": items_cfg.get("host", "127.0.0.1"),
                "port": items_cfg.get("port", 8770),
                "advertised_url": items_cfg.get("advertised_url", ""),
            },
        )
        return _ok(graph)

    async def save_settings(self):
        """改网关级设置：监听地址、端口、对外地址、访问令牌。"""
        payload = await _get_json()
        config = self._plugin.config
        gateway = config.get("gateway")
        if not isinstance(gateway, dict):
            gateway = {}
            config["gateway"] = gateway

        if "host" in payload:
            gateway["host"] = str(payload.get("host") or "127.0.0.1").strip()
        if "port" in payload:
            try:
                port = int(payload.get("port") or 8770)
            except (TypeError, ValueError):
                return _err("端口必须是数字")
            gateway["port"] = port if 1 <= port <= 65535 else 8770
        if "advertised_url" in payload:
            gateway["advertised_url"] = str(payload.get("advertised_url") or "").strip().rstrip("/")
        if "lb_strategy" in payload:
            strategy = str(payload.get("lb_strategy") or "round_robin").strip()
            gateway["lb_strategy"] = strategy if strategy in balancer_mod.STRATEGIES else "round_robin"
        if "log_retention_days" in payload:
            try:
                days = float(payload.get("log_retention_days"))
            except (TypeError, ValueError):
                days = 7.0
            gateway["log_retention_days"] = max(0.0, days)
        if "log_max_entries" in payload:
            try:
                count = int(payload.get("log_max_entries"))
            except (TypeError, ValueError):
                count = 500
            gateway["log_max_entries"] = max(1, count)
        token = payload.get("access_token")
        if token is not None:
            # 留空表示不改原来的令牌
            gateway["access_token"] = str(token) if str(token) else gateway.get("access_token", "")

        try:
            config.save_config()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[jev_gateway] 配置落盘失败: {exc}", exc_info=True)
            return _err(f"配置落盘失败：{exc}")

        await self._plugin.restart_server()
        return _ok({"endpoint_base": self._plugin.endpoint_base}, message="已保存并重启网关")

    async def save_entries(self):
        payload = await _get_json()
        raw = payload.get("entries")
        if not isinstance(raw, list):
            return _err("entries 必须是数组")

        # 空 Key 表示沿用原来的：明文 Key 不出后端，前端只拿到打码值
        existing: Dict[str, str] = {}
        for group in self._plugin._build_registry().values():
            for entry in group:
                existing.setdefault(entry.protocol, entry.api_key)

        entries: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                return _err(f"第 {index + 1} 条不是对象")
            protocol = str(item.get("protocol") or "").strip()
            if not protocol:
                return _err(f"第 {index + 1} 条缺协议名")
            if protocol in seen:
                return _err(f"协议名重复：{protocol}")
            seen.add(protocol)
            try:
                timeout = float(item.get("timeout") or 10)
            except (TypeError, ValueError):
                return _err(f"第 {index + 1} 条的超时不合法")
            kind = str(item.get("kind") or "systemone").strip()
            entries.append(
                {
                    "__template_key": kind if kind in ("systemone", "decisions", "custom") else "custom",
                    "protocol": protocol,
                    "base_url": str(item.get("base_url") or "").strip(),
                    "api_key": str(item.get("api_key") or "") or existing.get(protocol, ""),
                    "model": str(item.get("model") or "").strip(),
                    "endpoint_path": str(item.get("endpoint_path") or "").strip(),
                    "timeout": timeout,
                    "priority": _as_int(item.get("priority"), 100),
                    "weight": _as_int(item.get("weight"), 1),
                    "balance_url": str(item.get("balance_url") or "").strip(),
                    "balance_field": str(item.get("balance_field") or "").strip(),
                }
            )

        config = self._plugin.config
        gateway = config.get("gateway")
        if not isinstance(gateway, dict):
            gateway = {}
            config["gateway"] = gateway
        gateway["api_entries"] = entries
        try:
            config.save_config()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[jev_gateway] 配置落盘失败: {exc}", exc_info=True)
            return _err(f"配置落盘失败：{exc}")
        return _ok({"count": len(entries)}, message="已保存并即时生效")

    # ── 连通性测试 ──────────────────────────────────────────────
    async def test(self):
        payload = await _get_json()
        protocol = str(payload.get("protocol") or "").strip()
        if not protocol:
            return _err("缺少 protocol")
        port = self._plugin.server.port
        if not port:
            return _err("网关没在运行，先启用网关")

        state = payload.get("state")
        if not isinstance(state, str):
            state = "" if state is None else str(state)
        questions = payload.get("questions")
        if not isinstance(questions, dict) or not questions:
            return _err("questions 必须是非空对象")

        body = {
            "model": str(payload.get("model") or "").strip(),
            "state": state,
            "questions": questions,
        }
        body = {k: v for k, v in body.items() if v != ""}

        url = f"http://127.0.0.1:{port}/jev/{protocol}"
        headers = {"Content-Type": "application/json"}
        token = str(self._plugin._items().get("access_token") or "").strip()
        if token:
            headers["X-Jev-Gateway-Token"] = token

        import aiohttp

        started = time.perf_counter()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    raw = await response.read()
                    status = response.status
                    resp_headers = dict(response.headers)
        except Exception as exc:  # noqa: BLE001
            return _err(f"请求网关失败：{exc}")
        elapsed = round((time.perf_counter() - started) * 1000, 1)

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            parsed = None
        return _ok(
            {
                "status": status,
                "elapsed_ms": elapsed,
                "response": parsed if parsed is not None else raw.decode("utf-8", "replace"),
                "headers": {
                    k: v for k, v in resp_headers.items() if k.lower().startswith("x-")
                },
            }
        )

    # ── 余额 ────────────────────────────────────────────────────
    async def get_balance(self):
        port = self._plugin.server.port
        if not port:
            return _ok({"balances": {}}, message="网关没在运行")
        url = f"http://127.0.0.1:{port}/jev/balance"
        headers = {}
        token = str(self._plugin._items().get("access_token") or "").strip()
        if token:
            headers["X-Jev-Gateway-Token"] = token

        import aiohttp

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    data = await response.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            return _err(f"查询余额失败：{exc}")
        return _ok(data.get("balances", {}) if isinstance(data, dict) else {})


def register(context, plugin) -> None:
    """把网关的 WebUI API 注册到 AstrBot。"""
    api = GatewayAPI(plugin)
    routes = [
        (
            "/astrbot_plugin_jev_gateway/entries",
            api.get_entries,
            ["GET"],
            "网关入口列表与运行状态",
        ),
        (
            "/astrbot_plugin_jev_gateway/settings/save",
            api.save_settings,
            ["POST"],
            "保存网关监听设置（地址、端口、对外地址、令牌）",
        ),
        (
            "/astrbot_plugin_jev_gateway/entries/save",
            api.save_entries,
            ["POST"],
            "保存网关入口配置",
        ),
        (
            "/astrbot_plugin_jev_gateway/test",
            api.test,
            ["POST"],
            "通过网关发一次测试请求",
        ),
        (
            "/astrbot_plugin_jev_gateway/balance",
            api.get_balance,
            ["GET"],
            "查询各入口的余额",
        ),
        (
            "/astrbot_plugin_jev_gateway/topology",
            api.get_topology,
            ["GET"],
            "获取拓扑图数据（接入对象 / 网关 / API 入口）",
        ),
        (
            "/astrbot_plugin_jev_gateway/calls",
            api.get_calls,
            ["GET"],
            "获取最近的调用记录（提示词与结果）",
        ),
    ]
    for path, handler, methods, description in routes:
        context.register_web_api(path, handler, methods, description)
