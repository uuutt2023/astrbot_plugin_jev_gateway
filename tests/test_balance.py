"""余额追踪：响应里抠余额、自定义查询。"""

import json

import httpx
import pytest

from astrbot_plugin_jev_gateway.core import balance
from astrbot_plugin_jev_gateway.core import entries as entry_mod


def test_extract_from_token_header():
    unit, value = balance.extract_from_response({"X-Tokens-Remaining": "184320"}, b"")
    assert unit == "tokens"
    assert value == 184320.0


def test_extract_from_credits_body():
    body = json.dumps({"usage": {"credits_remaining_usd": 4.999974}}).encode()
    unit, value = balance.extract_from_response({}, body)
    assert unit == "usd"
    assert value == pytest.approx(4.999974)


def test_extract_returns_none_when_absent():
    assert balance.extract_from_response({}, b"{}") == (None, None)
    assert balance.extract_from_response({}, b"not json") == (None, None)


def test_extract_ignores_bad_header_value():
    assert balance.extract_from_response({"x-tokens-remaining": "abc"}, b"") == (None, None)


def test_tracker_records_and_snapshots():
    tracker = balance.BalanceTracker()
    tracker.record("systemone", "tokens", 100.0)
    tracker.record_response(
        "decisions", {}, json.dumps({"usage": {"credits_remaining_usd": 2.5}}).encode()
    )
    snap = tracker.snapshot()
    assert snap["systemone"]["value"] == 100.0
    assert snap["decisions"]["unit"] == "usd"
    assert tracker.get("nope") is None


def test_tracker_ignores_empty():
    tracker = balance.BalanceTracker()
    tracker.record("x", None, None)
    assert tracker.snapshot() == {}


def test_dig_supports_dotted_path():
    data = {"data": {"balance": {"usd": 3.5}}}
    assert balance._dig(data, "data.balance.usd") == 3.5
    assert balance._dig(data, "data.missing") is None
    assert balance._dig(data, "") is None


async def test_query_custom_reads_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"balance": 12.5}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    entry = entry_mod.parse_entry(
        {
            "protocol": "p",
            "base_url": "https://x",
            "balance_url": "https://x/balance",
            "balance_field": "data.balance",
        }
    )
    unit, value, error = await balance.query_custom(entry, client=client)
    await client.aclose()
    assert value == 12.5
    assert error == ""


async def test_query_custom_without_url():
    entry = entry_mod.parse_entry({"protocol": "p", "base_url": "https://x"})
    unit, value, error = await balance.query_custom(entry)
    assert value is None
    assert "未配置" in error


async def test_query_custom_missing_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"other": 1})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    entry = entry_mod.parse_entry(
        {
            "protocol": "p",
            "base_url": "https://x",
            "balance_url": "https://x/balance",
            "balance_field": "data.balance",
        }
    )
    unit, value, error = await balance.query_custom(entry, client=client)
    await client.aclose()
    assert value is None
    assert "没有字段" in error


async def test_query_custom_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    entry = entry_mod.parse_entry(
        {
            "protocol": "p",
            "base_url": "https://x",
            "balance_url": "https://x/balance",
            "balance_field": "balance",
        }
    )
    unit, value, error = await balance.query_custom(entry, client=client)
    await client.aclose()
    assert value is None
    assert "HTTP 500" in error


class TestBalancePerEntry:
    """同一协议登记多条入口时，余额要各记各的。"""

    def test_same_protocol_entries_keep_separate_balances(self):
        from astrbot_plugin_jev_gateway.core.balance import BalanceTracker

        tracker = BalanceTracker()
        tracker.record("a#0", "usd", 1.0)
        tracker.record("a#1", "usd", 2.0)
        snapshot = tracker.snapshot()
        assert snapshot["a#0"]["value"] == 1.0
        assert snapshot["a#1"]["value"] == 2.0
