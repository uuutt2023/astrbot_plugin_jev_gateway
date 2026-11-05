"""网关的独立 HTTP server：按协议名中转到对应上游入口。

路由：
- POST /jev/<协议名>   中转到该协议登记的入口
- POST /v1/systemone   systemone 协议的快捷入口（可作 AstrBot 判断提供商用）
- POST /v1/decisions   decisions 协议的快捷入口
- GET  /jev            列出已登记的入口
- GET  /health         存活检查
"""

from __future__ import annotations

import hashlib
import json
import time

from aiohttp import web

from . import balance as balance_mod
from . import balancer as balancer_mod
from . import calllog as calllog_mod
from . import entries as entry_mod
from . import relay
from . import topology as topology_mod

TOKEN_HEADER = "X-Jev-Gateway-Token"

#: 触发故障转移的上游状态码
FAILOVER_STATUSES = {502, 503, 504}

#: 去重缓存的存活时间（秒）
CACHE_TTL = 30.0

#: 算「这个入口自己出问题」的状态码：Key/余额/上游故障，换下一个入口有意义
ENTRY_FAULT_STATUSES = {401, 402, 403, 500, 502, 503, 504, 529}


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(payload, ensure_ascii=False),
        status=status,
        content_type="application/json",
    )


def _extract_prompt(body: bytes) -> tuple[str, dict]:
    """从请求体里抠出 state 与 questions，日志要记提示词。"""
    if not body:
        return "", {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    state = data.get("state")
    questions = data.get("questions")
    return (
        state if isinstance(state, str) else "",
        questions if isinstance(questions, dict) else {},
    )


def _is_loopback(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if not peer:
        return False
    host = str(peer[0]) if isinstance(peer, (tuple, list)) else str(peer)
    return host in ("127.0.0.1", "::1", "localhost")


class GatewayServer:
    """把请求按协议名中转的上游网关。"""

    def __init__(self, registry: dict[str, list[entry_mod.Entry]] | None = None,
                 access_token: str = "",
                 registry_provider=None):
        self._registry = registry or {}
        self._registry_provider = registry_provider
        self.access_token = access_token or ""
        self.balances = balance_mod.BalanceTracker()
        self.balancer = balancer_mod.Balancer()
        # 记录调用过网关的客户端插件，供 WebUI 的拓扑图用
        self.clients = topology_mod.ClientTracker()
        # 调用日志：提示词与结果都留一份，保留时长可配
        self.calllog = calllog_mod.CallLog()
        # 30 秒去重缓存：同协议同请求体短时间内只打一次上游
        self.cache: dict[str, tuple[float, int, dict, bytes, str]] = {}
        self.app = web.Application(client_max_size=64 * 1024 * 1024)
        self.app.router.add_post("/jev/{protocol}", self.handle_relay)
        self.app.router.add_post("/v1/systemone", self.handle_alias)
        self.app.router.add_post("/v1/decisions", self.handle_alias)
        self.app.router.add_get("/jev", self.handle_list)
        self.app.router.add_get("/jev/balance", self.handle_balance)
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
        """令牌只约束非本机来源。

        插件客户端只填「代理地址 + 协议名」两项，令牌由网关自己掌握；
        绑到 0.0.0.0 暴露给局域网时，非本机来源必须带对令牌。
        """
        if not self.access_token:
            return True
        if _is_loopback(request):
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

    async def handle_balance(self, request: web.Request) -> web.Response:
        """各入口的余额；配了自定义余额地址的入口顺带去查一次。"""
        balances = self.balances.snapshot()
        for entry in self._all_entries():
            if not entry.balance_url:
                continue
            unit, value, error = await balance_mod.query_custom(entry)
            if value is not None:
                balances[entry.id] = {
                    "unit": unit,
                    "value": value,
                    "source": "custom",
                    "protocol": entry.protocol,
                    "updated_at": time.time(),
                }
            elif entry.id not in balances:
                balances[entry.id] = {
                    "unit": None,
                    "value": None,
                    "source": "custom",
                    "protocol": entry.protocol,
                    "error": error,
                    "updated_at": time.time(),
                }
        return _json({"status": "ok", "balances": balances})

    def _all_entries(self) -> list:
        return [e for group in self.registry.values() for e in group]

    def _entries_for(self, protocol: str) -> list:
        """按协议类型找入口。

        客户端下拉里选的就是协议类型（SystemOne / OpenAI Decisions / Custom），
        同一类型可以登记多个入口，由负载均衡按优先级挑。没登记该类型时，
        再按「协议名」找一次，兼容按名字寻址的旧配置。
        """
        registry = self.registry
        by_kind = [e for e in self._all_entries() if e.kind == protocol]
        if by_kind:
            return by_kind
        return list(registry.get(protocol) or [])

    async def handle_alias(self, request: web.Request) -> web.Response:
        protocol = "systemone" if request.path.endswith("/systemone") else "decisions"
        return await self._relay(request, protocol)

    async def handle_relay(self, request: web.Request) -> web.Response:
        protocol = request.match_info.get("protocol", "")
        return await self._relay(request, protocol)

    async def _relay(self, request: web.Request, protocol: str) -> web.Response:
        if not self._authorized(request):
            return _json({"error": "unauthorized"}, 401)
        group = self._entries_for(protocol)
        if not group:
            known = sorted({e.kind for e in self._all_entries()})
            return _json(
                {
                    "error": f"protocol not registered: {protocol}",
                    "registered": known,
                },
                404,
            )
        body = await request.read()
        headers = dict(request.headers)
        client_name = request.headers.get(topology_mod.CLIENT_HEADER, "")
        prompt_state, prompt_questions = _extract_prompt(body)

        cache_key = f"{protocol}|{hashlib.sha256(body or b'').hexdigest()}"
        now = time.monotonic()
        cached = self.cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            _, status, resp_headers, resp_body, cached_entry_id = cached
            self.clients.record(client_name, protocol, ok=status == 200)
            self.calllog.record(
                client=client_name,
                protocol=protocol,
                entry_id=cached_entry_id,
                state=prompt_state,
                questions=prompt_questions,
                response=resp_body,
                status=status,
                cached=True,
            )
            return web.Response(body=resp_body, status=status, headers=resp_headers or None)

        candidates = await self.balancer.candidates(protocol, group)
        last: tuple[int, dict[str, str], bytes] = (502, {}, b'{"error":"no upstream"}')
        used_entry_id = ""
        relay_started = time.monotonic()
        for entry in candidates:
            started = time.monotonic()
            used_entry_id = entry.id
            last = await relay.forward(entry, request.method, headers, body)
            status, resp_headers, resp_body = last
            elapsed = time.monotonic() - started
            # 余额记在具体入口上：同协议的多条入口余额各算各的
            self.balances.record_response(entry.id, resp_headers or {}, resp_body or b"")
            last = (status, resp_headers, resp_body)
            if status == 200:
                self.balancer.record_success(entry.id, elapsed)
                break
            if status in ENTRY_FAULT_STATUSES:
                # 这个入口自己出了问题（Key/余额/上游），换下一个
                self.balancer.record_failure(entry.id)
                continue
            # 400/422 之类是请求本身的问题，换入口也没用
            break
        status, resp_headers, resp_body = last
        self.clients.record(client_name, protocol, ok=status == 200)
        self.calllog.record(
            client=client_name,
            protocol=protocol,
            entry_id=used_entry_id,
            state=prompt_state,
            questions=prompt_questions,
            response=resp_body,
            status=status,
            elapsed_ms=(time.monotonic() - relay_started) * 1000,
        )
        if status == 200:
            self.cache[cache_key] = (now, status, resp_headers or {}, resp_body, used_entry_id)
            self._trim_cache()
        return web.Response(
            body=resp_body,
            status=status,
            headers=resp_headers or None,
        )

    def _trim_cache(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self.cache.items() if now - v[0] >= CACHE_TTL]
        for key in stale:
            self.cache.pop(key, None)
