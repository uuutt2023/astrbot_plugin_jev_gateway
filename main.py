"""Jev 决策网关 —— 一处登记接口入口，多插件共用。

网关在本地起一个独立 HTTP 端口，收到请求后按「协议名」转发到对应的
Jev 接口，原样带回响应。其他插件只需填「代理地址 + 协议名」。
"""

from __future__ import annotations

import os

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core import entries as entry_mod
from .core.server import GatewayServer


def _plugin_version() -> str:
    """从 metadata.yaml 读版本号，避免与 @register 双处维护。"""
    try:
        path = os.path.join(os.path.dirname(__file__), "metadata.yaml")
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    except (OSError, ValueError):
        pass
    return "0.0.0"


@register(
    "astrbot_plugin_jev_gateway",
    "uuutt2023",
    "Jev 决策网关：一处配置 Key 与地址，多个插件按协议共用",
    _plugin_version(),
    "https://github.com/uuutt2023/astrbot_plugin_jev_gateway",
)
class JevGatewayPlugin(Star):
    """按协议中转 Jev 请求的本地网关。"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config if isinstance(config, dict) else {}
        self.server = GatewayServer(registry_provider=self._build_registry)

    # ── 配置 ────────────────────────────────────────────────────
    def _items(self) -> dict:
        gateway = self.config.get("gateway")
        if isinstance(gateway, dict):
            items = gateway.get("items")
            if isinstance(items, dict):
                return items
        return {}

    def _build_registry(self) -> dict[str, list[entry_mod.Entry]]:
        return entry_mod.build_registry(self._items().get("api_entries"))

    @property
    def endpoint_base(self) -> str:
        """客户端要填的代理地址。"""
        items = self._items()
        host = str(items.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        port = int(items.get("port") or 8770)
        return f"http://{host}:{port}"

    # ── 生命周期 ────────────────────────────────────────────────
    async def initialize(self):
        items = self._items()
        if not items.get("enabled", True):
            logger.info("[jev_gateway] 已禁用，不监听端口")
            return
        host = str(items.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(items.get("port") or 8770)
        except (TypeError, ValueError):
            port = 8770
        try:
            await self.server.start(host, port)
        except OSError as exc:
            logger.error(f"[jev_gateway] 端口 {host}:{port} 启动失败: {exc}")
            return
        registry = self._build_registry()
        logger.info(
            "[jev_gateway] 已启动 %s，登记协议: %s",
            self.endpoint_base,
            ", ".join(sorted(registry)) or "（空）",
        )

    async def terminate(self):
        await self.server.stop()
        logger.info("[jev_gateway] 已停止")

    # ── 指令 ────────────────────────────────────────────────────
    @filter.command("jev网关")
    async def cmd_gateway_status(self, event: AstrMessageEvent):
        """查看网关状态与已登记的入口。"""
        registry = self._build_registry()
        items = self._items()
        lines = [
            f"Jev 网关：{'运行中' if self.server.port else '未启动'}",
            f"代理地址：{self.endpoint_base}",
            f"访问令牌：{'已设置' if items.get('access_token') else '未设置（不校验）'}",
            "",
        ]
        if not registry:
            lines.append("尚未登记任何 API 入口。")
        for protocol, group in registry.items():
            primary = group[0]
            lines.append(f"• {protocol} → {primary.url or '（地址为空）'}")
            lines.append(f"    模型 {primary.model or '（跟随请求）'}  Key {primary.masked_key() or '（未填）'}")
            for extra in group[1:]:
                lines.append(f"    备用 → {extra.url or '（地址为空）'}")
        lines.append("")
        lines.append("其他插件填「代理地址 + 协议名」即可调用。")
        yield event.plain_result("\n".join(lines))
