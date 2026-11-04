"""转发层：请求体透传、鉴权替换、错误映射。"""

import httpx
import pytest

from astrbot_plugin_jev_gateway.core import entries, relay


def _entry(**kwargs):
    base = {"protocol": "systemone", "base_url": "https://up.example.com"}
    base.update(kwargs)
    return entries.parse_entry(base)


async def test_forward_passes_body_and_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["auth"] = request.headers.get("authorization")
        seen["custom"] = request.headers.get("x-extra")
        return httpx.Response(200, json={"answers": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, headers, body = await relay.forward(
        _entry(api_key="sk-gw", headers={"X-Extra": "yes"}),
        "POST",
        {"Authorization": "Bearer client-key", "Content-Type": "application/json"},
        b'{"model":"m"}',
        client=client,
    )
    await client.aclose()

    assert status == 200
    assert seen["url"] == "https://up.example.com/v1/systemone"
    assert seen["body"] == b'{"model":"m"}'
    assert seen["auth"] == "Bearer sk-gw"
    assert seen["custom"] == "yes"


async def test_forward_drops_client_auth_when_entry_has_no_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(
        _entry(),
        "POST",
        {"Authorization": "Bearer client-key"},
        b"{}",
        client=client,
    )
    await client.aclose()
    assert seen["auth"] is None


async def test_forward_injects_model_when_missing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(
        _entry(model="jev-latest"),
        "POST",
        {},
        b'{"questions":{}}',
        client=client,
    )
    await client.aclose()
    assert b"jev-latest" in seen["body"]


async def test_forward_keeps_model_from_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(
        _entry(model="jev-latest"),
        "POST",
        {},
        b'{"model":"mine"}',
        client=client,
    )
    await client.aclose()
    assert b"mine" in seen["body"] and b"jev-latest" not in seen["body"]


async def test_forward_returns_upstream_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "insufficient credits"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, body = await relay.forward(_entry(), "POST", {}, b"{}", client=client)
    await client.aclose()
    assert status == 402
    assert b"insufficient credits" in body


async def test_forward_timeout_maps_to_504():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, body = await relay.forward(_entry(), "POST", {}, b"{}", client=client)
    await client.aclose()
    assert status == 504
    assert b"timeout" in body


async def test_forward_connection_error_maps_to_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, _ = await relay.forward(_entry(), "POST", {}, b"{}", client=client)
    await client.aclose()
    assert status == 502


async def test_forward_without_base_url_is_400():
    status, _, _ = await relay.forward(_entry(base_url=""), "POST", {}, b"{}")
    assert status == 400


def test_build_headers_drops_hop_by_hop():
    entry = _entry(api_key="k")
    out = relay.build_headers(entry, {"Host": "x", "Connection": "keep-alive", "A": "b"})
    assert "Host" not in out and "Connection" not in out
    assert out["A"] == "b"
