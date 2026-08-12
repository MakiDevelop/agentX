"""Tests for the local-model benchmark harness.

These run offline against a scripted fake client. The point is that the
*instrument* is correct — if the harness miscounts, every measurement it
produces is worthless, and unlike a normal bug that failure is silent.
"""

from __future__ import annotations

from typing import Any

from agentx.benchmark import (
    BENCHMARK_CASES,
    BenchmarkCase,
    _parse_action,
    run_benchmark,
)

KNOWN_TOOLS = {"list_files", "read_file", "write_file", "git_status"}

TWO_CASES = (
    BenchmarkCase("a", "列出檔案", "tool_call", "list_files"),
    BenchmarkCase("b", "直接回答", "final", None),
)


class ScriptedClient:
    """Returns canned responses in order; records how many turns were asked."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        if not self.responses:
            return ""
        return self.responses.pop(0)


class ExplodingClient:
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise ConnectionError("backend down")


# --- parsing must match the loop ---------------------------------------------


def test_parses_clean_json() -> None:
    action, needed_repair = _parse_action('{"type":"final","content":"hi"}')

    assert action is not None
    assert needed_repair is False


def test_extracts_json_embedded_in_prose_but_flags_it() -> None:
    """The loop tolerates this, so the benchmark must too — while recording that
    raw compliance was worse than the headline number."""
    action, needed_repair = _parse_action(
        'Sure! {"type":"tool_call","tool":"list_files","args":{}} hope that helps'
    )

    assert action is not None
    assert needed_repair is True


def test_rejects_non_json() -> None:
    action, _ = _parse_action("I will now list the files for you.")

    assert action is None


def test_rejects_json_that_is_not_a_valid_action() -> None:
    """Valid JSON with a bogus schema is not a usable turn; the loop rejects it
    via pydantic and so must the benchmark."""
    action, _ = _parse_action('{"type":"tool_call","nope":1}')

    assert action is None


# --- metrics ------------------------------------------------------------------


def test_perfect_run_scores_one() -> None:
    client = ScriptedClient(
        [
            '{"type":"tool_call","tool":"list_files","args":{}}',
            '{"type":"final","content":"完成"}',
        ]
    )

    report = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES)
    metrics = report.payload()["metrics"]

    assert metrics["json_compliance"] == 1.0
    assert metrics["expectation_match"] == 1.0
    assert metrics["tool_exists"] == 1.0


def test_final_answers_do_not_count_against_tool_existence() -> None:
    """A turn that correctly declines to use a tool must not be scored as having
    named a non-existent one. (This was a real bug in the first version: a
    perfect run reported tool_exists=0.833.)"""
    client = ScriptedClient(
        [
            '{"type":"tool_call","tool":"list_files","args":{}}',
            '{"type":"final","content":"完成"}',
        ]
    )

    report = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES)

    assert report.payload()["metrics"]["tool_exists"] == 1.0


def test_hallucinated_tool_is_counted() -> None:
    client = ScriptedClient(
        [
            '{"type":"tool_call","tool":"definitely_not_a_tool","args":{}}',
            '{"type":"final","content":"完成"}',
        ]
    )

    metrics = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES).payload()[
        "metrics"
    ]

    assert metrics["tool_exists"] == 0.0
    assert metrics["expectation_match"] == 0.5


def test_unparseable_turn_triggers_a_correction_and_records_recovery() -> None:
    client = ScriptedClient(
        [
            "I'll list the files now.",  # case a: not JSON
            '{"type":"tool_call","tool":"list_files","args":{}}',  # recovery
            '{"type":"final","content":"完成"}',  # case b
        ]
    )

    payload = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES).payload()

    assert payload["metrics"]["json_compliance"] == 0.5
    assert payload["metrics"]["recovery_after_correction"] == 1.0
    assert client.calls == 3, "expected one retry turn"


def test_failure_to_recover_is_recorded() -> None:
    client = ScriptedClient(["still prose", "more prose", '{"type":"final","content":"完成"}'])

    payload = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES).payload()

    assert payload["metrics"]["recovery_after_correction"] == 0.0


def test_backend_error_is_a_datapoint_not_a_crash() -> None:
    """A dead backend must be measured, not raised: aborting on the first bad
    turn makes it impossible to see how bad things are."""
    payload = run_benchmark(
        ExplodingClient(), "sys", KNOWN_TOOLS, model="fake", cases=TWO_CASES
    ).payload()

    assert payload["case_count"] == 2
    assert payload["metrics"]["json_compliance"] == 0.0
    assert len(payload["notes"]) == 2


def test_ratio_is_none_when_nothing_was_measured() -> None:
    """None and 0.0 mean different things: 'not measured' vs 'measured, all
    wrong'. Reporting 0.0 for an unmeasured metric would look like a failure."""
    client = ScriptedClient(['{"type":"final","content":"完成"}'])
    single = (BenchmarkCase("only", "直接回答", "final", None),)

    metrics = run_benchmark(client, "sys", KNOWN_TOOLS, model="fake", cases=single).payload()[
        "metrics"
    ]

    assert metrics["tool_exists"] is None
    assert metrics["recovery_after_correction"] is None


# --- the pinned case set ------------------------------------------------------


def test_case_set_covers_previously_untaught_tools() -> None:
    """The first six cases could not tell the old and new prompts apart: both
    scored 1.000 because the model guessed common tool names. The set must keep
    cases whose tools cannot be guessed, or it silently stops discriminating."""
    expected = {case.expects_tool for case in BENCHMARK_CASES}

    assert "docker_compose_ps" in expected
    assert "web_fetch" in expected


def test_every_case_declares_a_valid_expectation() -> None:
    for case in BENCHMARK_CASES:
        assert case.expects_type in {"tool_call", "final", "reflect"}
        if case.expects_type != "tool_call":
            assert case.expects_tool is None, f"{case.name} expects a tool but is not a tool_call"
