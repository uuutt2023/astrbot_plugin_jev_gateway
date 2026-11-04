"""拓扑数据：接入对象（客户端插件）→ 网关 → API 入口。

WebUI 的「拓扑」页签画的就是这个图：
- 接入对象节点：调用过网关的客户端插件，带请求次数与协议
- 网关节点：网关自己，带监听地址与对外地址
- API 节点：登记的上游入口，带优先级、健康状态与请求统计
"""

from __future__ import annotations

import time

#: 客户端自报家门的请求头
CLIENT_HEADER = "X-Jev-Gateway-Client"

#: 超过这个时间没再来的客户端算「不活跃」（节点变灰，但保留）
ACTIVE_WINDOW = 300.0


class ClientTracker:
    """记录哪些客户端插件调用过网关。"""

    def __init__(self):
        self._clients: dict[str, dict] = {}

    def record(self, name: str, protocol: str = "", ok: bool = True) -> None:
        """记一次调用。名字为空就忽略（没带自报头的老客户端）。"""
        key = (name or "").strip()
        if not key:
            return
        item = self._clients.get(key)
        if item is None:
            item = self._clients[key] = {
                "name": key,
                "requests": 0,
                "errors": 0,
                "last_seen": 0.0,
                "protocols": {},
            }
        item["requests"] += 1
        if not ok:
            item["errors"] += 1
        item["last_seen"] = time.time()
        if protocol:
            item["protocols"][protocol] = item["protocols"].get(protocol, 0) + 1

    def snapshot(self) -> list[dict]:
        """当前登记的客户端，按最近活跃时间倒序。"""
        now = time.time()
        rows = []
        for item in self._clients.values():
            rows.append(
                {
                    "name": item["name"],
                    "requests": item["requests"],
                    "errors": item["errors"],
                    "last_seen": item["last_seen"],
                    "active": (now - item["last_seen"]) <= ACTIVE_WINDOW,
                    "protocols": dict(item["protocols"]),
                }
            )
        rows.sort(key=lambda row: (row["last_seen"], row["requests"]), reverse=True)
        return rows


def format_balance(unit: str | None, value: float | None) -> str:
    """把余额格式成人话，给图上的副标题用。"""
    if value is None:
        return "余额未知"
    if unit == "tokens":
        return f"余额 {value:,.0f} tokens"
    if unit == "usd":
        return f"余额 ${value:,.2f}"
    return f"余额 {value:g}"


def _source_text(source: str) -> str:
    if source == "custom":
        return "自定义查询"
    if source == "response":
        return "响应里带的"
    return source or "—"


def _time_text(timestamp: float) -> str:
    if not timestamp:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _client_label(name: str) -> str:
    """插件名太长，界面上只留好认的那截。"""
    for prefix in ("astrbot_plugin_", "astrbot_plugin-", "plugin_"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def build_graph(
    registry: dict[str, list],
    clients: ClientTracker,
    stats: dict | None = None,
    balances: dict | None = None,
    gateway: dict | None = None,
) -> dict:
    """拼出前端要的图结构。

    registry 是入口表（协议名 → 入口列表），clients 是客户端登记表，
    stats 是各入口的成败统计，balances 是各入口的余额，gateway 是网关自己的信息。
    """
    stats = stats or {}
    balances = balances or {}
    gateway = gateway or {}

    nodes: list[dict] = []
    edges: list[dict] = []

    nodes.append(
        {
            "id": "gateway",
            "kind": "gateway",
            "label": "Jev 决策网关",
            "detail": gateway.get("advertised_url") or gateway.get("host") or "",
            "meta": {
                "监听地址": gateway.get("host", ""),
                "监听端口": gateway.get("port", 0),
                "对外地址": gateway.get("advertised_url", ""),
            },
            "weight": 0,
        }
    )

    for group in registry.values():
        for entry in group:
            node_id = f"api:{entry.id}"
            stat = stats.get(entry.id) or {}
            balance = balances.get(entry.id) or {}
            nodes.append(
                {
                    "id": node_id,
                    "kind": "api",
                    "label": entry.protocol or entry.base_url,
                    "detail": entry.base_url,
                    "protocol": entry.kind,
                    "healthy": stat.get("healthy", True),
                    "requests": stat.get("success", 0) + stat.get("failure", 0),
                    "weight": max(1, entry.weight),
                    # 图上一直显示的副标题：余额
                    "sublabel": format_balance(balance.get("unit"), balance.get("value")),
                    "meta": {
                        "协议类型": entry.kind,
                        "接口地址": entry.url,
                        "优先级": entry.priority,
                        "权重": entry.weight,
                        "成功次数": stat.get("success", 0),
                        "失败次数": stat.get("failure", 0),
                        "失败率": stat.get("failure_rate", 0.0),
                        "平均耗时": stat.get("avg_latency", 0.0),
                        "状态": "正常" if stat.get("healthy", True) else "异常",
                        "余额": format_balance(balance.get("unit"), balance.get("value")),
                        "余额来源": _source_text(balance.get("source", "")),
                    },
                }
            )
            edges.append(
                {
                    "id": f"edge:{node_id}",
                    "source": "gateway",
                    "target": node_id,
                    "weight": max(1, stat.get("success", 0)),
                    "label": entry.kind,
                }
            )

    for client in clients.snapshot():
        node_id = f"client:{client['name']}"
        nodes.append(
            {
                "id": node_id,
                "kind": "client",
                "label": _client_label(client["name"]),
                "detail": client["name"],
                "active": client["active"],
                "requests": client["requests"],
                "weight": max(1, client["requests"]),
                "sublabel": f"{client['requests']} 次调用",
                "meta": {
                    "插件名": client["name"],
                    "调用次数": client["requests"],
                    "错误次数": client["errors"],
                    "使用协议": ", ".join(sorted(client["protocols"])) or "—",
                    "最近调用": _time_text(client["last_seen"]),
                    "状态": "活跃" if client["active"] else "不活跃",
                },
            }
        )
        edges.append(
            {
                "id": f"edge:{node_id}",
                "source": node_id,
                "target": "gateway",
                "weight": max(1, client["requests"]),
                "label": ", ".join(sorted(client["protocols"])),
            }
        )

    return {
        "gateway": {
            "label": "Jev 决策网关",
            "host": gateway.get("host", ""),
            "port": gateway.get("port", 0),
            "advertised_url": gateway.get("advertised_url", ""),
        },
        "nodes": nodes,
        "edges": edges,
        "updated_at": time.time(),
    }
