"""负载均衡：优先级分层、层内策略挑选、健康熔断。"""

import pytest

from astrbot_plugin_jev_gateway.core import balancer as balancer_mod
from astrbot_plugin_jev_gateway.core import entries as entry_mod


def _entry(name: str, url: str, priority: int = 100, weight: int = 1):
    entry = entry_mod.parse_entry(
        {
            "protocol": name,
            "base_url": url,
            "priority": priority,
            "weight": weight,
        }
    )
    return entry


def _entries():
    return [
        _entry("a", "https://a", priority=10, weight=3),
        _entry("b", "https://b", priority=10, weight=1),
        _entry("c", "https://c", priority=50, weight=1),
    ]


class TestPriority:
    async def test_higher_priority_comes_first(self):
        balancer = balancer_mod.Balancer()
        order = await balancer.candidates("x", _entries())
        assert order[0].priority == 10
        # 同级在前，低优先级在后
        assert [e.priority for e in order] == [10, 10, 50]

    async def test_candidates_cover_all_entries(self):
        balancer = balancer_mod.Balancer()
        order = await balancer.candidates("x", _entries())
        assert {e.base_url for e in order} == {"https://a", "https://b", "https://c"}

    async def test_empty_pool(self):
        balancer = balancer_mod.Balancer()
        assert await balancer.candidates("x", []) == []


class TestRoundRobin:
    async def test_rotates_between_same_priority(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_ROUND_ROBIN)
        picks = []
        for _ in range(4):
            order = await balancer.candidates("x", _entries())
            picks.append(order[0].base_url)
        assert picks.count("https://a") == 2
        assert picks.count("https://b") == 2

    async def test_round_robin_is_per_protocol(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_ROUND_ROBIN)
        await balancer.candidates("x", _entries())
        order = await balancer.candidates("y", _entries())
        assert order[0].base_url == "https://a"


class TestRandomAndWeighted:
    async def test_random_stays_in_top_tier(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_RANDOM)
        for _ in range(20):
            order = await balancer.candidates("x", _entries())
            assert order[0].priority == 10

    async def test_weighted_favours_heavier_entry(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_WEIGHTED)
        picks = []
        for _ in range(60):
            order = await balancer.candidates("x", _entries())
            picks.append(order[0].base_url)
        assert picks.count("https://a") > picks.count("https://b")

    async def test_weighted_ignores_zero_weight(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_WEIGHTED)
        entries = [_entry("a", "https://a", weight=0), _entry("b", "https://b", weight=1)]
        for _ in range(20):
            order = await balancer.candidates("x", entries)
            assert order[0].base_url == "https://b"


class TestLeastFailure:
    async def test_prefers_the_more_reliable_entry(self):
        balancer = balancer_mod.Balancer(balancer_mod.STRATEGY_LEAST_FAILURE)
        entries = [_entry("a", "https://a"), _entry("b", "https://b")]
        for _ in range(5):
            balancer.record_success(entries[0].id, 0.1)
            balancer.record_failure(entries[1].id)
        picks = []
        for _ in range(20):
            order = await balancer.candidates("x", entries)
            picks.append(order[0].base_url)
        assert picks.count("https://a") > picks.count("https://b")


class TestHealth:
    def test_failures_mark_entry_unhealthy(self):
        balancer = balancer_mod.Balancer()
        for _ in range(3):
            balancer.record_failure("a#0")
        assert balancer.is_healthy("a#0") is False

    def test_success_clears_the_failure_counter(self):
        balancer = balancer_mod.Balancer()
        balancer.record_failure("a#0")
        balancer.record_success("a#0")
        assert balancer.is_healthy("a#0") is True

    def test_unhealthy_entry_is_skipped(self):
        balancer = balancer_mod.Balancer()
        for _ in range(3):
            balancer.record_failure("a#0")
        assert balancer.is_healthy("a#0") is False
        assert balancer.is_healthy("b#1") is True

    async def test_all_unhealthy_still_tries_everyone(self):
        """全都不健康也照样试一遍：宁可多试一次也别直接失败。"""
        balancer = balancer_mod.Balancer()
        for entry in _entries():
            for _ in range(4):
                balancer.record_failure(entry.id)
        order = await balancer.candidates("x", _entries())
        assert len(order) == 3

    def test_snapshot_reports_rate(self):
        balancer = balancer_mod.Balancer()
        balancer.record_success("a#0", 0.2)
        balancer.record_failure("a#0")
        snap = balancer.snapshot()["a#0"]
        assert snap["success"] == 1
        assert snap["failure"] == 1
        assert snap["failure_rate"] == 0.5
        assert snap["avg_latency"] == pytest.approx(0.2)


class TestStrategyFallback:
    def test_unknown_strategy_falls_back_to_round_robin(self):
        assert balancer_mod.Balancer("nope").strategy == balancer_mod.STRATEGY_ROUND_ROBIN

    def test_all_strategies_are_known(self):
        for name in balancer_mod.STRATEGIES:
            assert balancer_mod.Balancer(name).strategy == name
