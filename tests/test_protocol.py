"""协议层契约：请求预检、错误映射、错误体解析、协议翻译。

这些逻辑原先散在三个插件各自的传输层里，现在统一在网关。
"""

from astrbot_plugin_jev_gateway.core import protocol


class TestValidator:
    def test_rejects_oversized_question_name(self):
        problems = protocol.validate_request(
            "x" * 10,
            {"q" * 65: {"type": "noul", "instructions": "x"}},
        )
        assert problems

    def test_rejects_empty_question_set(self):
        assert protocol.validate_request("state", {}) != []

    def test_rejects_missing_instructions(self):
        problems = protocol.validate_request("s", {"q": {"type": "noul"}})
        assert problems and "instructions" in problems[0]

    def test_rejects_unknown_type(self):
        problems = protocol.validate_request("s", {"q": {"type": "weird", "instructions": "x"}})
        assert problems and "type" in problems[0]

    def test_rejects_choice_with_one_option(self):
        problems = protocol.validate_request(
            "s", {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "A"}}}
        )
        assert problems

    def test_rejects_too_many_questions(self):
        questions = {f"q{i}": {"type": "noul", "instructions": "x"} for i in range(9)}
        problems = protocol.validate_request("s", questions)
        assert problems and "问题" in problems[0]

    def test_accepts_a_normal_request(self):
        problems = protocol.validate_request(
            "短状态",
            {"should_reply": {"type": "noul", "instructions": "Reply?"}},
        )
        assert problems == []

    def test_catches_real_state_overflow(self):
        huge_state = "x" * (protocol.MAX_STATE_CHARS + 10)
        problems = protocol.validate_request(
            huge_state, {"q": {"type": "noul", "instructions": "x"}}
        )
        assert problems and "state" in problems[0]

    def test_catches_real_criteria_overflow(self):
        huge_criteria = {"true": "y" * (protocol.MAX_CRITERIA_CHARS + 10)}
        problems = protocol.validate_request(
            "s",
            {"q": {"type": "noul", "instructions": "x", "criteria": huge_criteria}},
        )
        assert problems and "criteria" in problems[0]

    def test_fast_check_does_not_let_overflow_through(self):
        """快速判断只能跳过必然通过的检查，真正的超限必须照常拦下。"""
        huge_state = "x" * (protocol.MAX_STATE_CHARS + 10)
        problems = protocol.validate_request(
            huge_state, {"q": {"type": "noul", "instructions": "x"}}
        )
        assert problems


class TestErrorMapping:
    def test_status_mapping(self):
        assert protocol.error_status(401) == "unauthorized"
        assert protocol.error_status(402) == "insufficient_credits"
        assert protocol.error_status(403) == "forbidden"
        assert protocol.error_status(409) == "conflict"
        assert protocol.error_status(413) == "payload_too_large"
        assert protocol.error_status(422) == "invalid_request"
        assert protocol.error_status(429) == "rate_limited"
        assert protocol.error_status(500) == "upstream_error"
        assert protocol.error_status(502) == "upstream_error"

    def test_http_500_is_retryable(self):
        """很多网关在上游报错时返回 500 而不是 502——当不可重试会让偶发抖动直接失败。"""
        assert 500 in protocol.RETRYABLE_STATUS
        assert 502 in protocol.RETRYABLE_STATUS
        for status in (400, 401, 402, 403, 404, 422):
            assert status not in protocol.RETRYABLE_STATUS

    def test_error_body_is_parsed(self):
        kind, message = protocol.parse_error(
            {"error": {"type": "authentication_error", "message": "Invalid key"}}
        )
        assert kind == "authentication_error"
        assert message == "Invalid key"

    def test_error_body_as_plain_string(self):
        """中转网关常把 error 写成字符串（{"error": "Task request failed"}）。"""
        kind, message = protocol.parse_error({"error": "Task request failed"})
        assert kind == ""
        assert message == "Task request failed"

    def test_error_body_top_level_message(self):
        kind, message = protocol.parse_error({"message": "invalid api key"})
        assert message == "invalid api key"


class TestTranslation:
    def test_systemone_payload_shape(self):
        payload = protocol.build_payload(
            "m", "上下文", {"q": {"type": "noul", "instructions": "?"}}
        )
        assert payload["model"] == "m"
        assert payload["state"] == "上下文"
        assert payload["questions"]["q"]["type"] == "noul"

    def test_decisions_payload_shape(self):
        payload = protocol.build_payload(
            "m",
            {"a": 1},
            {"q": {"type": "choice", "instructions": "?", "criteria": {"x": "X"}}},
            protocol.API_FORMAT_DECISIONS,
        )
        assert payload["input"] == '{"a":1}'
        question = payload["questions"][0]
        assert question["type"] == "choice"
        assert question["choices"] == [{"value": "x", "description": "X"}]

    def test_decisions_noul_becomes_predicate(self):
        payload = protocol.build_payload(
            "m", "s", {"q": {"type": "noul", "instructions": "?"}}, protocol.API_FORMAT_DECISIONS
        )
        assert payload["questions"][0]["type"] == "predicate"

    def test_decisions_response_becomes_systemone(self):
        data = protocol.to_systemone_response(
            {
                "answers": [
                    {"name": "q", "type": "predicate", "probability": 0.6},
                    {
                        "name": "c",
                        "type": "choice",
                        "choice": "a",
                        "probabilities": [{"value": "a", "probability": 0.8}],
                    },
                ]
            }
        )
        assert data["answers"]["q"] == {"type": "noul", "noul": 0.6}
        assert data["answers"]["c"]["probabilities"]["a"] == 0.8

    def test_refusal_answer_is_skipped(self):
        data = protocol.to_systemone_response(
            {"answers": [{"name": "q", "type": "refusal", "refusal": "no"}]}
        )
        assert data["answers"] == {}

    def test_valid_answers_requires_all(self):
        data = {"answers": {"a": {}}}
        assert protocol.valid_answers(data, {"a": {}, "b": {}}) is False
        assert protocol.valid_answers(data, {"a": {}}) is True
