"""网关的独立 HTTP server：按协议名中转到对应上游入口。

路由：
- POST /jev/<协议名>   中转到该协议登记的入口
- POST /v1/systemone   systemone 协议的快捷入口（可作 AstrBot 判断提供商用）
- POST /v1/decisions   decisions 协议的快捷入口
- GET  /jev            列出已登记的入口
- GET  /health         存活检查
"""

from __future__ import annotations

import json

from aiohttp import web

from . import entries as entry_mod
from . import relay

TOKEN_HEADER = "X-Jev-Gateway-Token"

#: 触发故障转移的上游状态码
FAILOVER_STATUSES = {502, 503, 504}


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(payload, ensure_ascii=False),
        status=status,
        content_type="application/json",
    )


class GatewayServer:
    """把请求按协议名中转的上游网关。"""

    def __init__(self, registry: dict[str, list[entry_mod.Entry]] | None = None,
                 access_token: str = "",
                 registry_provider=None):
        self._registry = registry or {}
        self._registry_provider = registry_provider
        self.access_token = access_token or ""
        self.app = web.Application(client_max_size=64 * 1024 * 1024)
        self.app.router.add_post("/jev/{protocol}", self.handle_relay)
        self.app.router.add_post("/v1/systemone", self.handle_alias)
        self.app.router.add_post("/v1/decisions", self.handle_alias)
        self.app.router.add_get("/jev", self.handle_list)
        self.app.router.add_get("/health", self.handle_health)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # ── 生命周期 ────────────────────────────────────────────────
    @property
    def registry(self) -> dict[str, list[entry_mod.Entry]]:
        """当前入口表。配置变了立刻生效，不必重启网关。"""
        if self._registry_provider is not None:
            try:
                return self._registry_provider() or {}
            except Exception:  # noqa: BLE001 - 配置异常不该让网关整体挂掉
                return self._registry
        return self._registry

    async def start(self, host: str, port: int) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    @property
    def port(self) -> int | None:
        if self._site is None or self._site._server is None:
            return None
        return self._site._server.sockets[0].getsockname()[1]

    # ── 处理器 ──────────────────────────────────────────────────
    def _authorized(self, request: web.Request) -> bool:
        if not self.access_token:
            return True
        return request.headers.get(TOKEN_HEADER, "") == self.access_token

    async def handle_health(self, request: web.Request) -> web.Response:
        return _json({"status": "ok", "server": "jev_gateway"})

    async def handle_list(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return _json({"error": "unauthorized"}, 401)
        items = []
        for protocol, group in self.registry.items():
            for index, entry in enumerate(group):
                item = entry.describe()
                item["primary"] = index == 0
                items.append(item)
        return _json({"status": "ok", "entries": items})

    async def handle_alias(self, request: web.Request) -> web.Response:
        protocol = "systemone" if request.path.endswith("/systemone") else "decisions"
        return await self._relay(request, protocol)

    async def handle_relay(self, request: web.Request) -> web.Response:
        protocol = request.match_info.get("protocol", "")
        return await self._relay(request, protocol)

    async def _relay(self, request: web.Request, protocol: str) -> web.Response:
        if not self._authorized(request):
            return _json({"error": "unauthorized"}, 401)
        group = self.registry.get(protocol)
        if not group:
            known = sorted(self.registry)
            return _json(
                {
                    "error": f"protocol not registered: {protocol}",
                    "registered": known,
                },
                404,
            )
        body = await request.read()
        headers = dict(request.headers)
        last: tuple[int, dict[str, str], bytes] = (502, {}, b'{"error":"no upstream"}')
        for entry in group:
            last = await relay.forward(entry, request.method, headers, body)
            status = last[0]
            if status < 500 or status not in FAILOVER_STATUSES:
                break
        status, resp_headers, resp_body = last
        return web.Response(
            body=resp_body,
            status=status,
            headers=resp_headers or None,
        )
