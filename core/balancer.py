"""负载均衡：同一协议下的多个上游入口，按优先级分层、层内按策略挑选。

策略与健康判定参考 astrbot_plugin_lb_provider（轮询 / 随机 / 加权 / 最少失败），
只是选择对象从 LLM provider 换成了 Jev 上游入口。

优先级：数字越小越优先。同一优先级内的入口由策略挑选；挑中的排第一个，
失败后依次退到同级的下一个，再退到更低优先级。
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Iterable

STRATEGY_ROUND_ROBIN = "round_robin"
STRATEGY_RANDOM = "random"
STRATEGY_WEIGHTED = "weighted"
STRATEGY_LEAST_FAILURE = "least_failure"

STRATEGIES = (
    STRATEGY_ROUND_ROBIN,
    STRATEGY_RANDOM,
    STRATEGY_WEIGHTED,
    STRATEGY_LEAST_FAILURE,
)

STRATEGY_LABELS = {
    STRATEGY_ROUND_ROBIN: "轮询",
    STRATEGY_RANDOM: "随机",
    STRATEGY_WEIGHTED: "加权",
    STRATEGY_LEAST_FAILURE: "最少失败",
}

#: 失败率超过这个比例就临时摘掉该入口
FAILURE_RATE_THRESHOLD = 0.5
#: 一次都没成功过、失败到这个次数就摘掉
MAX_CONSECUTIVE_FAILURES = 3
#: 摘掉后多久重新参与（秒）
HEALTH_RECOVER_SECONDS = 60.0
#: 探索系数：越少被选中的入口，探索奖励越高
EXPLORATION_FACTOR = 2.0


class Balancer:
    """挑选上游入口并记账健康状况。"""

    def __init__(self, strategy: str = STRATEGY_ROUND_ROBIN):
        self.strategy = strategy if strategy in STRATEGIES else STRATEGY_ROUND_ROBIN
        self._stats: dict[str, dict] = {}
        self._unhealthy_until: dict[str, float] = {}
        self._rr_index: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # ── 健康 ────────────────────────────────────────────────────
    def is_healthy(self, entry_id: str) -> bool:
        until = self._unhealthy_until.get(entry_id)
        if until is None:
            return True
        if time.monotonic() >= until:
            # 冷却期过了，放回来重新试
            self._unhealthy_until.pop(entry_id, None)
            stat = self._stats.get(entry_id)
            if stat is not None:
                stat["failure"] = 0
            return True
        return False

    def record_success(self, entry_id: str, elapsed: float = 0.0) -> None:
        stat = self._stats.setdefault(
            entry_id, {"success": 0, "failure": 0, "latency_sum": 0.0}
        )
        stat["success"] += 1
        stat["latency_sum"] += max(0.0, elapsed)
        stat["failure"] = max(0, stat["failure"] - 1)
        self._unhealthy_until.pop(entry_id, None)

    def record_failure(self, entry_id: str) -> None:
        stat = self._stats.setdefault(
            entry_id, {"success": 0, "failure": 0, "latency_sum": 0.0}
        )
        stat["failure"] += 1
        total = stat["success"] + stat["failure"]
        failure_rate = stat["failure"] / total if total else 0.0
        if failure_rate > FAILURE_RATE_THRESHOLD or (
            stat["failure"] >= MAX_CONSECUTIVE_FAILURES and stat["success"] == 0
        ):
            self._unhealthy_until[entry_id] = time.monotonic() + HEALTH_RECOVER_SECONDS

    def snapshot(self) -> dict:
        """给 WebUI 展示用的统计。"""
        out = {}
        for entry_id, stat in self._stats.items():
            total = stat["success"] + stat["failure"]
            out[entry_id] = {
                "success": stat["success"],
                "failure": stat["failure"],
                "failure_rate": round(stat["failure"] / total, 3) if total else 0.0,
                "avg_latency": round(stat["latency_sum"] / stat["success"], 3)
                if stat["success"]
                else 0.0,
                "healthy": self.is_healthy(entry_id),
            }
        return out

    # ── 选择 ────────────────────────────────────────────────────
    async def candidates(self, protocol: str, entries: Iterable) -> list:
        """排出候选顺序：策略选中的排第一，然后同级其余，再退到低优先级。

        entries 需要有 .id / .priority / .weight 属性。
        """
        pool = list(entries)
        if not pool:
            return []
        healthy = [e for e in pool if self.is_healthy(e.id)]
        # 全都不健康就照样都试一遍：宁可多试一次，也别直接给用户一个失败
        usable = healthy or pool
        usable.sort(key=lambda e: (e.priority, e.index))

        top_priority = usable[0].priority
        same = [e for e in usable if e.priority == top_priority]
        others = [e for e in usable if e.priority != top_priority]

        picked = await self._pick(protocol, same)
        if picked is not None and same:
            same = [picked] + [e for e in same if e.id != picked.id]
        return same + others

    async def _pick(self, protocol: str, entries: list):
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0]
        if self.strategy == STRATEGY_RANDOM:
            return random.choice(entries)
        if self.strategy == STRATEGY_WEIGHTED:
            return self._pick_weighted(entries)
        if self.strategy == STRATEGY_LEAST_FAILURE:
            return self._pick_least_failure(entries)
        return await self._pick_round_robin(protocol, entries)

    async def _pick_round_robin(self, protocol: str, entries: list):
        async with self._lock:
            index = self._rr_index.get(protocol, 0)
            self._rr_index[protocol] = (index + 1) % len(entries)
        return entries[index % len(entries)]

    def _pick_weighted(self, entries: list):
        weighted = []
        total = 0
        for entry in entries:
            weight = max(0, int(entry.weight or 0))
            if weight <= 0:
                continue
            total += weight
            weighted.append((entry, total))
        if not weighted:
            return random.choice(entries)
        point = random.randint(0, total - 1)
        for entry, end in weighted:
            if point < end:
                return entry
        return weighted[-1][0]

    def _pick_least_failure(self, entries: list):
        """成功率高的优先；没人被选过的给探索奖励，避免一直只用第一个。"""
        scored = []
        for entry in entries:
            stat = self._stats.get(entry.id, {"success": 0, "failure": 0})
            total = stat["success"] + stat["failure"]
            base = (stat["success"] / total) if total else 1.0
            if total > 0:
                bonus = EXPLORATION_FACTOR * math.sqrt(math.log(total + 1) / total)
            else:
                bonus = EXPLORATION_FACTOR * 10
            scored.append((entry, base + bonus))
        total_score = sum(score for _, score in scored)
        if total_score <= 0:
            return random.choice(entries)
        point = random.uniform(0, total_score)
        acc = 0.0
        for entry, score in scored:
            acc += score
            if point <= acc:
                return entry
        return scored[-1][0]
