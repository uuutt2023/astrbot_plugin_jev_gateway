"""网关路由：按协议中转、鉴权、故障转移。"""

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_jev_gateway.core import entries
from astrbot_plugin_jev_gateway.core.server import GatewayServer


async def _fake_forward(entry, method, headers, body):
    return 200, {}, b"{}"


@pytest.fixture
async def client():
    registry = entries.build_registry(
        [
            {"protocol": "systemone", "base_url": "https://up1", "api_key": "k1"},
            {"protocol": "decisions", "base_url": "https://up2", "endpoint_path": "/v1/decisions"},
        ]
    )
    server = GatewayServer(registry=registry)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    yield test_client
    await test_client.close()


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status == 200
    assert (await resp.json())["status"] == "ok"


async def test_list_entries(client):
    resp = await client.get("/jev")
    data = await resp.json()
    protocols = [e["protocol"] for e in data["entries"]]
    assert "systemone" in protocols and "decisions" in protocols


async def test_list_does_not_leak_key(client):
    resp = await client.get("/jev")
    body = await resp.text()
    assert "k1" not in body


async def test_relay_by_protocol(client, monkeypatch):
    seen = {}

    async def fake_forward(entry, method, headers, body):
        seen["entry"] = entry
        seen["body"] = body
        return 200, {"content-type": "application/json"}, b'{"answers":{}}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    resp = await client.post("/jev/decisions", data=b'{"questions":{}}')
    assert resp.status == 200
    assert seen["entry"].protocol == "decisions"
    assert seen["entry"].url == "https://up2/v1/decisions"


async def test_unknown_protocol_returns_404(client):
    resp = await client.post("/jev/nope", data=b"{}")
    assert resp.status == 404
    data = await resp.json()
    assert "systemone" in data["registered"]


async def test_alias_paths(client, monkeypatch):
    seen = {}

    async def fake_forward(entry, method, headers, body):
        seen["protocol"] = entry.protocol
        return 200, {}, b"{}"

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    await client.post("/v1/systemone", data=b"{}")
    assert seen["protocol"] == "systemone"


async def test_token_not_required_from_loopback(monkeypatch):
    """本机来的请求免检——客户端插件只填代理地址与协议名两项。"""
    registry = entries.build_registry([{"protocol": "p", "base_url": "https://up"}])
    server = GatewayServer(registry=registry, access_token="secret")
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.core.server.relay.forward",
        _fake_forward,
    )
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/p", data=b"{}")
        assert resp.status == 200
    finally:
        await test_client.close()


async def test_token_required_from_remote(monkeypatch):
    registry = entries.build_registry([{"protocol": "p", "base_url": "https://up"}])
    server = GatewayServer(registry=registry, access_token="secret")
    monkeypatch.setattr(
        "astrbot_plugin_jev_gateway.core.server._is_loopback", lambda request: False
    )
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/p", data=b"{}")
        assert resp.status == 401
        resp = await test_client.post(
            "/jev/p", data=b"{}", headers={"X-Jev-Gateway-Token": "secret"}
        )
        assert resp.status != 401
    finally:
        await test_client.close()


async def test_failover_to_next_entry(monkeypatch):
    registry = entries.build_registry(
        [
            {"protocol": "p", "base_url": "https://primary"},
            {"protocol": "p", "base_url": "https://backup"},
        ]
    )
    server = GatewayServer(registry=registry)
    tried = []

    async def fake_forward(entry, method, headers, body):
        tried.append(entry.base_url)
        if entry.base_url == "https://primary":
            return 503, {}, b'{"error":"up"}'
        return 200, {}, b'{"ok":true}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/p", data=b"{}")
        assert resp.status == 200
        assert tried == ["https://primary", "https://backup"]
    finally:
        await test_client.close()


async def test_auth_failure_fails_over(monkeypatch):
    """401 是这个入口的 Key 不对，换下一个入口有意义。"""
    registry = entries.build_registry(
        [
            {"protocol": "p", "base_url": "https://primary"},
            {"protocol": "p", "base_url": "https://backup"},
        ]
    )
    server = GatewayServer(registry=registry)
    tried = []

    async def fake_forward(entry, method, headers, body):
        tried.append(entry.base_url)
        if entry.base_url == "https://primary":
            return 401, {}, b'{"error":"unauthorized"}'
        return 200, {}, b'{"ok":true}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/p", data=b"{}")
        assert resp.status == 200
        assert tried == ["https://primary", "https://backup"]
    finally:
        await test_client.close()


async def test_no_failover_on_4xx(monkeypatch):
    registry = entries.build_registry(
        [
            {"protocol": "p", "base_url": "https://primary"},
            {"protocol": "p", "base_url": "https://backup"},
        ]
    )
    server = GatewayServer(registry=registry)
    tried = []

    async def fake_forward(entry, method, headers, body):
        tried.append(entry.base_url)
        return 422, {}, b'{"error":"invalid request"}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/p", data=b"{}")
        assert resp.status == 422
        assert tried == ["https://primary"]
    finally:
        await test_client.close()


async def test_registry_provider_is_used_each_request(monkeypatch):
    state = {"entries": [{"protocol": "first", "base_url": "https://a"}]}
    server = GatewayServer(registry_provider=lambda: entries.build_registry(state["entries"]))

    async def fake_forward(entry, method, headers, body):
        return 200, {}, entry.protocol.encode()

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post("/jev/first", data=b"{}")
        assert (await resp.text()) == "first"
        state["entries"] = [{"protocol": "second", "base_url": "https://b"}]
        resp = await test_client.post("/jev/second", data=b"{}")
        assert (await resp.text()) == "second"
    finally:
        await test_client.close()


async def test_client_header_is_recorded(monkeypatch):
    """客户端自报家门，网关记下来给拓扑图用。"""
    registry = entries.build_registry(
        [{"protocol": "p", "base_url": "https://primary"}]
    )
    server = GatewayServer(registry=registry)

    async def fake_forward(entry, method, headers, body):
        return 200, {}, b'{"ok":true}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        resp = await test_client.post(
            "/jev/p",
            data=b"{}",
            headers={"X-Jev-Gateway-Client": "astrbot_plugin_soupai"},
        )
        assert resp.status == 200
        rows = server.clients.snapshot()
        assert len(rows) == 1
        assert rows[0]["name"] == "astrbot_plugin_soupai"
        assert rows[0]["requests"] == 1
        assert rows[0]["protocols"] == {"p": 1}
    finally:
        await test_client.close()


async def test_request_without_client_header_is_not_recorded(monkeypatch):
    registry = entries.build_registry(
        [{"protocol": "p", "base_url": "https://primary"}]
    )
    server = GatewayServer(registry=registry)

    async def fake_forward(entry, method, headers, body):
        return 200, {}, b'{"ok":true}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        await test_client.post("/jev/p", data=b"{}")
        assert server.clients.snapshot() == []
    finally:
        await test_client.close()


async def test_balance_is_recorded_per_entry(monkeypatch):
    """同协议的两条入口，余额各记各的，不能混。"""
    registry = entries.build_registry(
        [
            {"protocol": "p", "kind": "systemone", "base_url": "https://a", "priority": 10},
            {"protocol": "p2", "kind": "systemone", "base_url": "https://b", "priority": 20},
        ]
    )
    server = GatewayServer(registry=registry)

    async def fake_forward(entry, method, headers, body):
        # 第一条返回 503 触发故障转移，第二条才真的成功
        if entry.base_url == "https://a":
            return 503, {"X-Tokens-Remaining": "111"}, b'{"error":"boom"}'
        return 200, {"X-Tokens-Remaining": "222"}, b'{"ok":true}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        await test_client.post("/jev/systemone", data=b"{}")
    finally:
        await test_client.close()

    snapshot = server.balances.snapshot()
    values = {key: item["value"] for key, item in snapshot.items()}
    assert set(values.values()) == {111.0, 222.0}, values


async def test_call_is_recorded_with_prompt_and_result(monkeypatch):
    """每次调用都要在日志里留下提示词与结果。"""
    registry = entries.build_registry(
        [{"protocol": "p", "kind": "systemone", "base_url": "https://primary"}]
    )
    server = GatewayServer(registry=registry)

    async def fake_forward(entry, method, headers, body):
        return 200, {}, b'{"answers": {"should_reply": {"type": "noul", "noul": 0.8}}}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        body = json.dumps({
            "state": "群里有人问问题",
            "questions": {"should_reply": {"type": "noul", "instructions": "该回吗？"}},
        }).encode()
        resp = await test_client.post(
            "/jev/systemone",
            data=body,
            headers={"X-Jev-Gateway-Client": "astrbot_plugin_soupai"},
        )
        assert resp.status == 200
    finally:
        await test_client.close()

    rows = server.calllog.snapshot()
    assert len(rows) == 1
    row = rows[0]
    assert row["client"] == "astrbot_plugin_soupai"
    assert row["protocol"] == "systemone"
    assert "该回吗？" in row["prompt"]
    assert row["state"] == "群里有人问问题"
    assert row["status"] == 200
    assert row["result"] == "should_reply=0.8"


async def test_dedup_hit_is_logged_as_cached(monkeypatch):
    """命中 30 秒去重缓存的请求也要留痕，并标出是缓存命中。"""
    registry = entries.build_registry(
        [{"protocol": "p", "kind": "systemone", "base_url": "https://primary"}]
    )
    server = GatewayServer(registry=registry)

    async def fake_forward(entry, method, headers, body):
        return 200, {}, b'{"answers": {"should_reply": {"type": "noul", "noul": 0.8}}}'

    monkeypatch.setattr("astrbot_plugin_jev_gateway.core.server.relay.forward", fake_forward)
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    try:
        body = json.dumps({
            "state": "同样的内容",
            "questions": {"should_reply": {"type": "noul", "instructions": "该回吗？"}},
        }).encode()
        await test_client.post("/jev/systemone", data=body)
        await test_client.post("/jev/systemone", data=body)
    finally:
        await test_client.close()

    rows = server.calllog.snapshot()
    assert len(rows) == 2
    assert rows[0]["cached"] is True
    assert rows[1]["cached"] is False
