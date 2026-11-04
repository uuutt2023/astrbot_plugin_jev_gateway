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
    gateway: dict | None = None,
) -> dict:
    """拼出前端要的图结构。

    registry 是入口表（协议名 → 入口列表），clients 是客户端登记表，
    stats 是各入口的成败统计，gateway 是网关自己的信息。
    """
    stats = stats or {}
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
                "host": gateway.get("host", ""),
                "port": gateway.get("port", 0),
                "advertised_url": gateway.get("advertised_url", ""),
            },
            "weight": 0,
        }
    )

    for group in registry.values():
        for entry in group:
            node_id = f"api:{entry.id}"
            stat = stats.get(entry.id) or {}
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
                    "meta": {
                        "protocol": entry.kind,
                        "url": entry.url,
                        "priority": entry.priority,
                        "weight": entry.weight,
                        "success": stat.get("success", 0),
                        "failure": stat.get("failure", 0),
                        "failure_rate": stat.get("failure_rate", 0.0),
                        "avg_latency": stat.get("avg_latency", 0.0),
                        "healthy": stat.get("healthy", True),
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
                "meta": {
                    "name": client["name"],
                    "requests": client["requests"],
                    "errors": client["errors"],
                    "last_seen": client["last_seen"],
                    "active": client["active"],
                    "protocols": ", ".join(sorted(client["protocols"])),
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
