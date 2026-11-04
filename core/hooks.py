"""中间处理钩子：请求进来 → 转发前 → 上游响应 → 返回前。

内置钩子只做两件小事（补 model、脱敏日志）。要加定制逻辑，
在插件目录下放一个 hooks_ext.py，实现下面任一函数即可自动加载：

    async def before_forward(entry, ctx) -> dict | None
    async def after_response(entry, ctx) -> dict | None

ctx 是普通 dict：
- before_forward: {"method", "path", "headers", "body"}
- after_response:  {"status", "headers", "body"}

返回 dict 覆盖对应字段（headers/body/status），返回 None 表示不干预。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

#: 上游返回里要透传给客户端的响应头
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

#: 客户端请求里不该转发给上游的头
DROP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

_EXT: object | None = None


def _load_ext():
    """加载插件目录下的 hooks_ext.py（可选）。"""
    global _EXT
    if _EXT is not None:
        return _EXT
    _EXT = False
    path = Path(__file__).resolve().parent.parent / "hooks_ext.py"
    if not path.exists():
        return _EXT
    try:
        spec = importlib.util.spec_from_file_location("jev_gateway_hooks_ext", path)
        if spec is None or spec.loader is None:
            return _EXT
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _EXT = module
    except Exception:  # noqa: BLE001 - 扩展失败不能拖垮网关
        _EXT = False
    return _EXT


async def before_forward(entry, ctx: dict) -> dict | None:
    """转发前改写请求。内置：body 没有 model 时补上入口配置的模型。"""
    patched = _inject_model(entry, ctx)
    ext = _load_ext()
    if ext and hasattr(ext, "before_forward"):
        patched = await ext.before_forward(entry, ctx) or patched
    return patched


async def after_response(entry, ctx: dict) -> dict | None:
    """返回前改写响应。"""
    ext = _load_ext()
    if ext and hasattr(ext, "after_response"):
        return await ext.after_response(entry, ctx)
    return None


def _inject_model(entry, ctx: dict) -> dict | None:
    body = ctx.get("body")
    if not body or entry.model == "":
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("model"):
        return None
    data["model"] = entry.model
    return {"body": json.dumps(data, ensure_ascii=False).encode("utf-8")}


def strip_hop_by_hop(headers: dict[str, str]) -> dict[str, str]:
    """去掉逐跳首部，只留端到端的。"""
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}
