"""入口注册表：解析、路由、URL 拼接。"""

from astrbot_plugin_jev_gateway.core import entries


def test_parse_entry_reads_template_key():
    entry = entries.parse_entry(
        {"__template_key": "decisions", "protocol": "decisions", "base_url": "https://x"}
    )
    assert entry.kind == entries.KIND_DECISIONS


def test_parse_entry_defaults_to_systemone():
    entry = entries.parse_entry({"protocol": "p", "base_url": "https://x"})
    assert entry.kind == entries.KIND_SYSTEMONE


def test_parse_entry_drops_missing_protocol():
    assert entries.parse_entry({"base_url": "https://x"}) is None


def test_parse_entry_drops_non_dict():
    assert entries.parse_entry("nope") is None


def test_unknown_kind_becomes_custom():
    entry = entries.parse_entry({"protocol": "p", "kind": "weird"})
    assert entry.kind == entries.KIND_CUSTOM


def test_url_uses_default_path_per_kind():
    assert entries.parse_entry(
        {"protocol": "p", "kind": "systemone", "base_url": "https://x"}
    ).url == "https://x/v1/systemone"
    assert entries.parse_entry(
        {"protocol": "p", "kind": "decisions", "base_url": "https://x"}
    ).url == "https://x/v1/decisions"


def test_url_uses_custom_path():
    entry = entries.parse_entry(
        {"protocol": "p", "base_url": "https://x", "endpoint_path": "/api/v1/decide"}
    )
    assert entry.url == "https://x/api/v1/decide"


def test_url_does_not_double_path():
    entry = entries.parse_entry(
        {"protocol": "p", "base_url": "https://x/v1/systemone", "kind": "systemone"}
    )
    assert entry.url == "https://x/v1/systemone"


def test_url_without_base_is_empty():
    assert entries.parse_entry({"protocol": "p"}).url == ""


def test_registry_groups_by_protocol():
    raw = [
        {"protocol": "a", "base_url": "https://1"},
        {"protocol": "a", "base_url": "https://2"},
        {"protocol": "b", "base_url": "https://3"},
    ]
    registry = entries.build_registry(raw)
    assert list(registry) == ["a", "b"]
    assert len(registry["a"]) == 2


def test_resolve_returns_primary():
    registry = entries.build_registry(
        [{"protocol": "a", "base_url": "https://1"}, {"protocol": "a", "base_url": "https://2"}]
    )
    assert entries.resolve(registry, "a").base_url == "https://1"


def test_resolve_unknown_protocol_is_none():
    registry = entries.build_registry([{"protocol": "a", "base_url": "https://1"}])
    assert entries.resolve(registry, "zzz") is None


def test_failovers_exclude_primary():
    registry = entries.build_registry(
        [{"protocol": "a", "base_url": "https://1"}, {"protocol": "a", "base_url": "https://2"}]
    )
    assert [e.base_url for e in entries.failovers(registry, "a")] == ["https://2"]


def test_masked_key_hides_middle():
    entry = entries.parse_entry({"protocol": "p", "api_key": "sk-1234567890"})
    assert entry.masked_key() == "sk-1...7890"


def test_masked_key_short():
    entry = entries.parse_entry({"protocol": "p", "api_key": "abc"})
    assert entry.masked_key() == "***"


def test_describe_has_no_plain_key():
    entry = entries.parse_entry({"protocol": "p", "api_key": "sk-secret-value"})
    assert "sk-secret-value" not in str(entry.describe())


def test_build_registry_ignores_non_list():
    assert entries.build_registry("nope") == {}
