"""WebUI 后端 API：入口列表、保存（空 Key 保持原值）、测试请求、余额。"""

import json

import pytest

from astrbot_plugin_jev_gateway.core import entries as entry_mod
from astrbot_plugin_jev_gateway.core.server import GatewayServer
from astrbot_plugin_jev_gateway.web_api import GatewayAPI


class FakeConfig(dict):
    """能存盘的假配置。"""

    def __init__(self, data):
        super().__init__(data)
        self.saved = 0

    def save_config(self):
        self.saved += 1


def _plugin(tmp_path, entries=None, host="127.0.0.1", port=8770):
    from astrbot_plugin_jev_gateway.main import JevGatewayPlugin

    raw = entries if entries is not None else [
        {
            "__template_key": "systemone",
            "protocol": "systemone",
            "base_url": "https://jevmodel.org",
            "api_key": "sk-secret",
            "model": "jev-latest",
        }
    ]
    config = FakeConfig(
        {"gateway": {"enabled": True, "host": host, "port": port, "api_entries": raw}}
    )
    plugin = JevGatewayPlugin(None, config)
    plugin.config = config
    return plugin


@pytest.fixture
def api(tmp_path):
    plugin = _plugin(tmp_path)
    return GatewayAPI(plugin), plugin


async def test_entries_list_masks_key(api):
    api_obj, _ = api
    result = await _call(api_obj.get_entries)
    data = _data(result)
    assert data["entries"][0]["protocol"] == "systemone"
    assert "sk-secret" not in json.dumps(data, ensure_ascii=False)
    assert data["entries"][0]["key_masked"]


async def test_entries_list_shows_runtime_state(api):
    api_obj, _ = api
    result = await _call(api_obj.get_entries)
    data = _data(result)
    assert data["running"] is False
    assert data["endpoint_base"] == "http://127.0.0.1:8770"


async def test_save_entries_keeps_existing_key(api, monkeypatch):
    api_obj, plugin = api
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub({"entries": [{"protocol": "systemone", "base_url": "https://new"}]}),
    )
    result = await _call(api_obj.save_entries)
    assert _data(result)["count"] == 1
    saved = plugin.config["gateway"]["api_entries"]
    assert saved[0]["api_key"] == "sk-secret"
    assert saved[0]["base_url"] == "https://new"
    assert plugin.config.saved == 1


async def test_save_entries_sets_new_key(api, monkeypatch):
    api_obj, plugin = api
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub(
            {
                "entries": [
                    {"protocol": "p", "base_url": "https://x", "api_key": "sk-new"}
                ]
            }
        ),
    )
    await _call(api_obj.save_entries)
    assert plugin.config["gateway"]["api_entries"][0]["api_key"] == "sk-new"


async def test_save_entries_rejects_duplicate_protocol(api, monkeypatch):
    api_obj, _ = api
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub(
            {
                "entries": [
                    {"protocol": "a", "base_url": "https://x"},
                    {"protocol": "a", "base_url": "https://y"},
                ]
            }
        ),
    )
    result = await _call(api_obj.save_entries)
    assert _is_error(result)


async def test_save_entries_rejects_missing_protocol(api, monkeypatch):
    api_obj, _ = api
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub({"entries": [{"base_url": "https://x"}]}),
    )
    result = await _call(api_obj.save_entries)
    assert _is_error(result)


async def test_test_requires_gateway_running(api, monkeypatch):
    api_obj, _ = api
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub({"protocol": "systemone", "questions": {"q": {"type": "noul"}}}),
    )
    result = await _call(api_obj.test)
    assert _is_error(result)


async def test_test_goes_through_gateway(api, monkeypatch):
    api_obj, plugin = api
    registry = entry_mod.build_registry(
        [{"protocol": "systemone", "base_url": "https://up", "api_key": "k"}]
    )
    plugin.server = GatewayServer(registry=registry)
    await plugin.server.start("127.0.0.1", 0)

    seen = {}

    async def fake_forward(entry, method, headers, body):
        seen["path"] = entry.url
        seen["body"] = body
        return 200, {"content-type": "application/json"}, b'{"answers":{}}'

    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward
    )
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.web_api._get_json",
        _json_stub(
            {
                "protocol": "systemone",
                "state": "上下文",
                "questions": {"q": {"type": "noul", "instructions": "?"}},
            }
        ),
    )
    try:
        result = await _call(api_obj.test)
        data = _data(result)
        assert data["status"] == 200
        assert seen["path"] == "https://up/v1/systemone"
        assert b"questions" in seen["body"]
    finally:
        await plugin.server.stop()


async def test_balance_returns_empty_when_not_running(api):
    api_obj, _ = api
    result = await _call(api_obj.get_balance)
    assert _data(result) == {"balances": {}}


# ── 小工具 ────────────────────────────────────────────────────────
async def _call(handler):
    """兼容新版 astrbot.api.web 与 quart 两种返回形态。"""
    result = handler()
    if hasattr(result, "__await__"):
        result = await result
    return result


def _data(result):
    if isinstance(result, dict):
        return result.get("data", result)
    body = result.get_json() if hasattr(result, "get_json") else result.body
    if isinstance(body, bytes):
        body = json.loads(body.decode())
    return body.get("data", body)


def _is_error(result) -> bool:
    if isinstance(result, dict):
        return result.get("status") == "error"
    body = result.get_json() if hasattr(result, "get_json") else result.body
    if isinstance(body, bytes):
        body = json.loads(body.decode())
    return body.get("status") == "error"


def _json_stub(payload):
    async def _get_json():
        return payload

    return _get_json
