"""转发层：内部请求体 → 按入口协议翻译 → 上游 → 翻译回 SystemOne。"""

import json

import httpx
import pytest

from astrbot_plugin_jev_gateway.core import entries, protocol, relay

INTERNAL = json.dumps(
    {
        "model": "m",
        "state": "群里的对话",
        "questions": {
            "should_reply": {"type": "noul", "instructions": "Reply?"},
            "which": {"type": "choice", "instructions": "Which?", "criteria": {"a": "A", "b": "B"}},
        },
    }
).encode("utf-8")


def _entry(**kwargs):
    base = {"protocol": "systemone", "base_url": "https://up.example.com"}
    base.update(kwargs)
    return entries.parse_entry(base)


async def test_forward_passes_state_and_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"answers": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, headers, body = await relay.forward(
        _entry(api_key="sk-gw"), "POST", {"Authorization": "Bearer client-key"}, INTERNAL, client=client
    )
    await client.aclose()

    assert status == 200
    assert seen["url"] == "https://up.example.com/v1/systemone"
    assert seen["body"]["state"] == "群里的对话"
    assert seen["body"]["questions"]["should_reply"]["type"] == "noul"
    assert seen["auth"] == "Bearer sk-gw"


async def test_forward_drops_client_auth_when_entry_has_no_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(_entry(), "POST", {"Authorization": "Bearer client-key"}, INTERNAL, client=client)
    await client.aclose()
    assert seen["auth"] is None


async def test_forward_injects_model_when_missing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    body = json.dumps({"state": "x", "questions": {"q": {"type": "noul", "instructions": "?"}}}).encode()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(_entry(model="jev-latest"), "POST", {}, body, client=client)
    await client.aclose()
    assert seen["body"]["model"] == "jev-latest"


async def test_forward_keeps_model_from_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(_entry(model="jev-latest"), "POST", {}, INTERNAL, client=client)
    await client.aclose()
    assert seen["body"]["model"] == "m"


async def test_decisions_entry_gets_translated_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await relay.forward(
        _entry(kind="decisions", endpoint_path="/v1/decisions"),
        "POST",
        {},
        INTERNAL,
        client=client,
    )
    await client.aclose()

    body = seen["body"]
    assert "input" in body and "state" not in body
    assert body["input"] == "群里的对话"
    names = {q["name"]: q for q in body["questions"]}
    assert names["should_reply"]["type"] == "predicate"
    assert names["which"]["choices"] == [
        {"value": "a", "description": "A"},
        {"value": "b", "description": "B"},
    ]


async def test_decisions_response_translated_back_to_systemone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": [
                    {"name": "should_reply", "type": "predicate", "probability": 0.8},
                    {
                        "name": "which",
                        "type": "choice",
                        "choice": "a",
                        "probabilities": [{"value": "a", "probability": 0.7}],
                        "confidence": 0.7,
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, body = await relay.forward(
        _entry(kind="decisions"), "POST", {}, INTERNAL, client=client
    )
    await client.aclose()

    data = json.loads(body)
    assert status == 200
    assert data["answers"]["should_reply"] == {"type": "noul", "noul": 0.8}
    assert data["answers"]["which"]["choice"] == "a"
    assert data["answers"]["which"]["probabilities"]["a"] == 0.7


async def test_systemone_response_is_untouched():
    payload = {"answers": {"should_reply": {"type": "noul", "noul": 0.9}}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _, _, body = await relay.forward(_entry(), "POST", {}, INTERNAL, client=client)
    await client.aclose()
    assert json.loads(body) == payload


async def test_invalid_body_is_rejected_locally():
    status, _, body = await relay.forward(_entry(), "POST", {}, b"{}", None)
    assert status == 400
    data = json.loads(body)
    assert data["status"] == "invalid_request"
    assert data["problems"]


async def test_empty_body_is_rejected():
    status, _, _ = await relay.forward(_entry(), "POST", {}, b"", None)
    assert status == 400


async def test_forward_returns_upstream_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "insufficient credits"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, body = await relay.forward(_entry(), "POST", {}, INTERNAL, client=client)
    await client.aclose()
    assert status == 402
    assert b"insufficient credits" in body


async def test_forward_timeout_maps_to_504():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, body = await relay.forward(_entry(), "POST", {}, INTERNAL, client=client)
    await client.aclose()
    assert status == 504
    assert b"timeout" in body


async def test_forward_connection_error_maps_to_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, _ = await relay.forward(_entry(), "POST", {}, INTERNAL, client=client)
    await client.aclose()
    assert status == 502


async def test_retryable_status_is_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"answers": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status, _, _ = await relay.forward(_entry(), "POST", {}, INTERNAL, client=client, retries=1)
    await client.aclose()
    assert calls["n"] == 2
    assert status == 200


async def test_forward_without_base_url_is_400():
    status, _, _ = await relay.forward(_entry(base_url=""), "POST", {}, INTERNAL)
    assert status == 400


def test_upstream_format_by_kind():
    assert relay.upstream_format(_entry(kind="systemone")) == protocol.API_FORMAT_SYSTEMONE
    assert relay.upstream_format(_entry(kind="decisions")) == protocol.API_FORMAT_DECISIONS
    assert relay.upstream_format(_entry(kind="custom")) == protocol.API_FORMAT_SYSTEMONE


def test_build_headers_drops_hop_by_hop():
    out = relay.build_headers(_entry(api_key="k"), {"Host": "x", "Connection": "keep-alive", "A": "b"})
    assert "Host" not in out and "Connection" not in out
    assert out["A"] == "b"
