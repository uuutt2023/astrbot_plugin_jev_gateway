"""pytest 公共装置：最小 AstrBot 桩件 + 包路径。

网关的 core 模块不依赖 AstrBot，只有 main.py 需要；桩件只提供真正用到的
那几个名字。运行：``pytest tests/ -q``
"""

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _install_astrbot_stub():
    if "astrbot" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")

    class _Any:
        """万能占位：属性访问与调用都返回自己。"""

        def __getattr__(self, name):
            return _Any()

        def __call__(self, *args, **kwargs):
            def deco(func):
                return func

            if len(args) == 1 and not kwargs and callable(args[0]):
                return args[0]
            return deco

    class _Filter:
        def command(self, *args, **kwargs):
            def deco(func):
                func.__filter_cmd__ = True
                return func

            if len(args) == 1 and not kwargs and callable(args[0]):
                return args[0]
            return deco

        def __getattr__(self, name):
            return _Any()

    class AstrMessageEvent:
        pass

    class Context:
        pass

    class Star:
        def __init__(self, context=None, *args, **kwargs):
            self.context = context

    def register(*args, **kwargs):
        def deco(cls):
            return cls

        if len(args) == 1 and not kwargs and callable(args[0]):
            return args[0]
        return deco

    event.filter = _Filter()
    event.AstrMessageEvent = AstrMessageEvent
    star.Context = Context
    star.Star = Star
    star.register = register

    # astrbot.api.web（4.27+）：WebUI 后端 API 用的那套
    web = types.ModuleType("astrbot.api.web")

    class _WebRequest:
        async def json(self, default=None):
            return default

    # 真实实现是把 payload 原样作为响应体，这里保持一致
    def json_response(data=None, status=200, **kwargs):
        return data

    def error_response(message="", status_code=400, **kwargs):
        return {"status": "error", "message": message, "data": {}}

    web.request = _WebRequest()
    web.json_response = json_response
    web.error_response = error_response

    api.event = event
    api.star = star
    api.web = web
    api.logger = __import__("logging").getLogger("astrbot.stub")
    api.AstrBotConfig = dict
    astrbot.api = api

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.api.web": web,
        }
    )


_install_astrbot_stub()

# 插件以包方式导入：把仓库根目录的父目录放进 sys.path
_PARENT = str(ROOT.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

PLUGIN_PKG = ROOT.name


@pytest.fixture(scope="session")
def plugin_module():
    """导入 main.py（此时 astrbot 已被桩件顶替）。"""
    import importlib

    return importlib.import_module(f"{PLUGIN_PKG}.main")


@pytest.fixture
def make_plugin(plugin_module):
    """造一个带配置的插件实例。"""

    def _make(items=None, enabled=True):
        # 框架给插件的是摊平后的结构：分组的 items 直接挂在分组键下
        cfg = {"gateway": {"enabled": enabled, **(items or {})}}
        return plugin_module.JevGatewayPlugin(None, cfg)

    return _make


@pytest.fixture
def registry():
    from astrbot_plugin_jev_gateway.core import entries

    return entries.build_registry(
        [
            {
                "__template_key": "systemone",
                "protocol": "systemone",
                "base_url": "https://jevmodel.org",
                "api_key": "sk-test",
                "model": "jev-latest",
            },
            {
                "__template_key": "decisions",
                "protocol": "decisions",
                "base_url": "https://gw.example.com",
                "endpoint_path": "/v1/decisions",
            },
            {
                "__template_key": "custom",
                "protocol": "my-custom",
                "base_url": "https://custom.example.com",
                "endpoint_path": "/api/v1/decide",
            },
        ]
    )
