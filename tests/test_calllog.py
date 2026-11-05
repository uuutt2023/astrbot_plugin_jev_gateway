"""调用日志：提示词与结果留档、按时间过期。"""

import time

from astrbot_plugin_jev_gateway.core import calllog as calllog_mod

QUESTIONS = {
    "should_reply": {
        "type": "noul",
        "instructions": "Should the assistant reply right now?",
    }
}


def _record(log, **kwargs):
    payload = {
        "client": "astrbot_plugin_soupai",
        "protocol": "systemone",
        "entry_id": "systemone#0",
        "state": "群里有人问问题",
        "questions": QUESTIONS,
        "response": b'{"answers": {"should_reply": {"type": "noul", "noul": 0.9}}}',
        "status": 200,
        "elapsed_ms": 812.0,
    }
    payload.update(kwargs)
    return log.record(**payload)


class TestRecord:
    def test_records_prompt_and_result(self):
        log = calllog_mod.CallLog()
        item = _record(log)
        assert item["client"] == "astrbot_plugin_soupai"
        assert item["protocol"] == "systemone"
        assert "Should the assistant reply right now?" in item["prompt"]
        assert item["result"] == "should_reply=0.9"
        assert item["response"]["answers"]["should_reply"]["noul"] == 0.9
        assert item["status"] == 200

    def test_prompt_lists_every_question(self):
        log = calllog_mod.CallLog()
        questions = {
            "a": {"type": "noul", "instructions": "问题 A"},
            "b": {"type": "choice", "instructions": "问题 B"},
        }
        item = _record(log, questions=questions)
        assert "a: 问题 A" in item["prompt"]
        assert "b: 问题 B" in item["prompt"]

    def test_long_state_is_truncated(self):
        log = calllog_mod.CallLog()
        item = _record(log, state="x" * (calllog_mod.MAX_STATE_CHARS + 500))
        assert len(item["state"]) <= calllog_mod.MAX_STATE_CHARS + 1
        assert item["truncated"] is True

    def test_non_json_response_keeps_text(self):
        log = calllog_mod.CallLog()
        item = _record(log, response=b"not json")
        assert item["response"] == "not json"
        assert item["result"] == ""

    def test_cached_flag_is_kept(self):
        log = calllog_mod.CallLog()
        item = _record(log, cached=True)
        assert item["cached"] is True


class TestSnapshot:
    def test_newest_first(self):
        log = calllog_mod.CallLog()
        _record(log, client="a")
        _record(log, client="b")
        rows = log.snapshot()
        assert rows[0]["client"] == "b"
        assert rows[1]["client"] == "a"

    def test_filter_by_client(self):
        log = calllog_mod.CallLog()
        _record(log, client="a")
        _record(log, client="b")
        rows = log.snapshot(client="a")
        assert len(rows) == 1
        assert rows[0]["client"] == "a"

    def test_limit(self):
        log = calllog_mod.CallLog()
        for _ in range(5):
            _record(log)
        assert len(log.snapshot(limit=2)) == 2


class TestRetention:
    def test_expired_entries_are_pruned(self):
        log = calllog_mod.CallLog(retention_seconds=60)
        _record(log)
        # 把这条记录的时间挪到过期之前
        log._items[0]["at"] = time.time() - 3600
        log.prune()
        assert log.snapshot() == []

    def test_configure_changes_retention(self):
        log = calllog_mod.CallLog()
        log.configure(retention_seconds=7 * 86400)
        assert log.retention_seconds == 7 * 86400
        assert log.stats()["retention_days"] == 7

    def test_zero_retention_keeps_everything(self):
        log = calllog_mod.CallLog()
        log.configure(retention_seconds=0)
        _record(log)
        log._items[0]["at"] = time.time() - 99999
        log.prune()
        assert len(log.snapshot()) == 1

    def test_max_entries_bounds_the_log(self):
        log = calllog_mod.CallLog(max_entries=3)
        for _ in range(10):
            _record(log)
        assert len(log.snapshot(limit=100)) == 3

    def test_configure_can_shrink_max_entries(self):
        log = calllog_mod.CallLog(max_entries=10)
        for _ in range(10):
            _record(log)
        log.configure(max_entries=4)
        assert len(log.snapshot(limit=100)) == 4

    def test_default_retention_is_seven_days(self):
        assert calllog_mod.CallLog().retention_seconds == 7 * 86400
        assert calllog_mod.DEFAULT_RETENTION_DAYS == 7.0
