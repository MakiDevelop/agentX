import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, reliability_suite_payload
from agentx.config import Settings


def test_reliability_suite_payload_runs_recorded_cases(tmp_path: Path) -> None:
    payload = reliability_suite_payload(Settings(workspace=tmp_path), run_id="recorded")

    assert payload["schema"] == "agentx.reliability_suite.v1"
    assert payload["ok"] is True
    assert payload["run_id"] == "recorded"
    assert payload["case_count"] == 3
    assert payload["passed"] == 3
    assert payload["failed"] == 0
    cases = {case["name"]: case for case in payload["cases"]}  # type: ignore[index]
    assert set(cases) == {"edit_file", "inspect_only", "recover_after_failure"}
    assert cases["edit_file"]["tool_call_count"] == 1
    assert cases["inspect_only"]["tool_call_count"] == 1
    assert cases["recover_after_failure"]["tool_call_count"] == 2
    for case in cases.values():
        assert case["ok"] is True
        assert case["exit_code"] == 0
        assert case["termination"] == "final_success"
        assert case["artifact_complete"] is True
        assert isinstance(case["gate_recommended_kind"], str)
        assert case["gate_recommended_kind"]
        artifact_dir = Path(str(case["artifact_dir"]))
        assert (artifact_dir / "result.json").is_file()
        assert (artifact_dir / "session.session.jsonl").is_file()
        assert (artifact_dir / "handoff.md").is_file()


def test_reliability_suite_json_outputs_payload(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "reliability-suite",
            "--workspace",
            str(tmp_path),
            "--run-id",
            "cli-json",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.reliability_suite.v1"
    assert payload["ok"] is True
    assert payload["case_count"] == 3
    assert payload["recommended_kind"] == "inspect"


def test_reliability_suite_jsonl_outputs_event(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "reliability-suite",
            "--workspace",
            str(tmp_path),
            "--run-id",
            "cli-jsonl",
            "--case",
            "edit",
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "reliability_suite"
    assert envelope["data"]["schema"] == "agentx.reliability_suite.v1"
    assert envelope["data"]["case_count"] == 1
    assert envelope["data"]["cases"][0]["name"] == "edit_file"


def test_reliability_suite_blocks_unknown_case(tmp_path: Path) -> None:
    payload = reliability_suite_payload(Settings(workspace=tmp_path), run_id="none", case_filter="missing")

    assert payload["ok"] is False
    assert payload["blockers"] == ["no_matching_cases"]
    assert payload["case_count"] == 0
