"""拓扑数据：客户端登记表与图结构。"""

from astrbot_plugin_jev_gateway.core import entries as entry_mod
from astrbot_plugin_jev_gateway.core import topology as topology_mod


class TestClientTracker:
    def test_records_client(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("astrbot_plugin_soupai", "systemone")
        tracker.record("astrbot_plugin_soupai", "systemone")
        rows = tracker.snapshot()
        assert len(rows) == 1
        assert rows[0]["name"] == "astrbot_plugin_soupai"
        assert rows[0]["requests"] == 2
        assert rows[0]["protocols"] == {"systemone": 2}
        assert rows[0]["errors"] == 0

    def test_ignores_empty_name(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("", "systemone")
        assert tracker.snapshot() == []

    def test_counts_errors(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("a", "systemone", ok=False)
        assert tracker.snapshot()[0]["errors"] == 1

    def test_marks_inactive_after_window(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("a", "systemone")
        row = tracker.snapshot()[0]
        assert row["active"] is True
        # 把最后一次访问时间推到很久以前
        tracker._clients["a"]["last_seen"] -= topology_mod.ACTIVE_WINDOW + 10
        assert tracker.snapshot()[0]["active"] is False

    def test_snapshot_sorted_by_last_seen(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("old", "systemone")
        tracker.record("new", "systemone")
        rows = tracker.snapshot()
        assert rows[0]["name"] == "new"


class TestBuildGraph:
    def _registry(self):
        return entry_mod.build_registry(
            [
                {"protocol": "systemone", "kind": "systemone", "base_url": "https://a"},
                {"protocol": "systemone-b", "kind": "systemone", "base_url": "https://b"},
                {"protocol": "decisions", "kind": "decisions", "base_url": "https://c"},
            ]
        )

    def test_contains_gateway_api_and_client(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("astrbot_plugin_soupai", "systemone")
        graph = topology_mod.build_graph(self._registry(), tracker)

        kinds = [node["kind"] for node in graph["nodes"]]
        assert kinds.count("gateway") == 1
        assert kinds.count("api") == 3
        assert kinds.count("client") == 1

    def test_edges_link_client_to_gateway_and_gateway_to_api(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("astrbot_plugin_soupai", "systemone")
        graph = topology_mod.build_graph(self._registry(), tracker)

        client_edges = [e for e in graph["edges"] if e["source"].startswith("client:")]
        api_edges = [e for e in graph["edges"] if e["target"].startswith("api:")]
        assert len(client_edges) == 1
        assert client_edges[0]["target"] == "gateway"
        assert len(api_edges) == 3
        assert all(e["source"] == "gateway" for e in api_edges)

    def test_client_label_strips_plugin_prefix(self):
        tracker = topology_mod.ClientTracker()
        tracker.record("astrbot_plugin_angel_heart", "systemone")
        graph = topology_mod.build_graph(self._registry(), tracker)
        client = [n for n in graph["nodes"] if n["kind"] == "client"][0]
        assert client["label"] == "angel_heart"
        assert client["detail"] == "astrbot_plugin_angel_heart"

    def test_api_node_carries_priority_and_health(self):
        tracker = topology_mod.ClientTracker()
        graph = topology_mod.build_graph(self._registry(), tracker, {"systemone#0": {
            "success": 3, "failure": 1, "failure_rate": 0.25, "healthy": True,
        }})
        api = [n for n in graph["nodes"] if n["kind"] == "api"][0]
        assert api["healthy"] is True
        assert api["requests"] == 4
        assert api["meta"]["success"] == 3

    def test_unhealthy_entry_is_marked(self):
        tracker = topology_mod.ClientTracker()
        graph = topology_mod.build_graph(
            self._registry(), tracker, {"systemone#0": {"success": 0, "failure": 3, "healthy": False}}
        )
        api = [n for n in graph["nodes"] if n["kind"] == "api"][0]
        assert api["healthy"] is False

    def test_empty_graph_still_has_gateway(self):
        graph = topology_mod.build_graph({}, topology_mod.ClientTracker())
        assert len(graph["nodes"]) == 1
        assert graph["nodes"][0]["kind"] == "gateway"
        assert graph["edges"] == []
