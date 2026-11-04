"""端到端：网关 → 假上游，真跑一遍 HTTP。"""

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_jev_gateway.core import entries
from astrbot_plugin_jev_gateway.core.server import GatewayServer


@pytest.fixture
async def upstream():
    """假 Jev 上游：回显收到的请求。"""
    received = {}

    async def handle(request: web.Request) -> web.Response:
        received["path"] = request.path
        received["body"] = await request.read()
        received["auth"] = request.headers.get("authorization")
        received["model"] = (await request.json()).get("model") if received["body"] else None
        return web.json_response({"answers": {"ok": {"type": "noul", "noul": 0.9}}})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    client = TestClient(TestServer(app))
    await client.start_server()
    received["base"] = str(client.make_url("/")).rstrip("/")
    yield received
    await client.close()


async def test_end_to_end_relay(upstream):
    registry = entries.build_registry(
        [
            {
                "protocol": "systemone",
                "base_url": upstream["base"],
                "api_key": "sk-gateway",
                "model": "jev-latest",
            }
        ]
    )
    server = GatewayServer(registry=registry)
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        resp = await client.post(
            "/jev/systemone",
            json={"questions": {"q": {"type": "noul"}}},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["answers"]["ok"]["noul"] == 0.9
        assert upstream["path"] == "/v1/systemone"
        assert upstream["auth"] == "Bearer sk-gateway"
        assert upstream["model"] == "jev-latest"
    finally:
        await client.close()


async def test_end_to_end_custom_endpoint(upstream):
    registry = entries.build_registry(
        [
            {
                "protocol": "custom",
                "base_url": upstream["base"],
                "endpoint_path": "/api/v1/decide",
            }
        ]
    )
    server = GatewayServer(registry=registry)
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        resp = await client.post("/jev/custom", json={"questions": {}})
        assert resp.status == 200
        assert upstream["path"] == "/api/v1/decide"
    finally:
        await client.close()


async def test_upstream_error_is_passed_through(upstream):
    async def handle(request: web.Request) -> web.Response:
        return web.json_response({"error": "insufficient credits"}, status=402)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        base = str(client.make_url("/")).rstrip("/")
        registry = entries.build_registry(
            [{"protocol": "p", "base_url": base, "api_key": "k"}]
        )
        server = GatewayServer(registry=registry)
        gw = TestClient(TestServer(server.app))
        await gw.start_server()
        try:
            resp = await gw.post("/jev/p", json={})
            assert resp.status == 402
            assert "insufficient credits" in await resp.text()
        finally:
            await gw.close()
    finally:
        await client.close()
