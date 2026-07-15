import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, reliability_decision_payload, reliability_profile_payload, reliability_suite_payload
from agentx.config import Settings
from agentx.provider_registry import register_llm_backend


def test_reliability_suite_payload_runs_recorded_cases(tmp_path: Path) -> None:
    payload = reliability_suite_payload(Settings(workspace=tmp_path), run_id="recorded")

    assert payload["schema"] == "agentx.reliability_suite.v1"
    assert payload["ok"] is True
    assert payload["run_id"] == "recorded"
    assert payload["case_count"] == 4
    assert payload["passed"] == 4
    assert payload["failed"] == 0
    assert payload["target_bar"]["schema"] == "agentx.reliability_target_bar.v1"  # type: ignore[index]
    assert payload["target_bar"]["profile"] == "recorded-v1"  # type: ignore[index]
    assert payload["target_bar"]["status"] == "proposed"  # type: ignore[index]
    assert payload["target_bar"]["ratification_required"] is True  # type: ignore[index]
    assert payload["target_bar"]["meets_proposed_threshold"] is True  # type: ignore[index]
    assert payload["target_bar"]["observed_pass_rate"] == 1.0  # type: ignore[index]
    assert payload["target_bar"]["missing_required_cases"] == []  # type: ignore[index]
    assert payload["target_bar"]["failed_cases"] == []  # type: ignore[index]
    assert payload["target_bar"]["failed_required_checks"] == {}  # type: ignore[index]
    cases = {case["name"]: case for case in payload["cases"]}  # type: ignore[index]
    assert set(cases) == {"edit_file", "inspect_only", "recover_after_failure", "artifact_resume"}
    assert cases["edit_file"]["tool_call_count"] == 1
    assert cases["inspect_only"]["tool_call_count"] == 1
    assert cases["recover_after_failure"]["tool_call_count"] == 2
    assert cases["artifact_resume"]["tool_call_count"] == 1
    assert cases["artifact_resume"]["exit_code"] == 2
    assert cases["artifact_resume"]["termination"] == "max_steps_exceeded"
    assert cases["artifact_resume"]["next_recommended_kind"] == "handoff_resume"
    assert cases["artifact_resume"]["artifacts_recommended_kind"] == "handoff_resume"
    assert cases["artifact_resume"]["handoff_resume"]["field"] == "resume_command"  # type: ignore[index]
    assert cases["artifact_resume"]["handoff_resume"]["argv"][0] == "agentx"  # type: ignore[index]
    assert "--prompt-file" in cases["artifact_resume"]["handoff_resume"]["argv"]  # type: ignore[index]
    assert "--resume-session" in cases["artifact_resume"]["handoff_resume"]["argv"]  # type: ignore[index]
    for case in cases.values():
        assert case["ok"] is True
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
    assert payload["case_count"] == 4
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
    assert envelope["data"]["target_bar"]["meets_proposed_threshold"] is False
    assert set(envelope["data"]["target_bar"]["missing_required_cases"]) == {
        "inspect_only",
        "recover_after_failure",
        "artifact_resume",
    }
    assert envelope["data"]["recommended_kind"] == "run_full_reliability_suite"


def test_reliability_suite_blocks_unknown_case(tmp_path: Path) -> None:
    payload = reliability_suite_payload(Settings(workspace=tmp_path), run_id="none", case_filter="missing")

    assert payload["ok"] is False
    assert payload["blockers"] == ["no_matching_cases"]
    assert payload["case_count"] == 0
    assert payload["target_bar"]["meets_proposed_threshold"] is False  # type: ignore[index]
    assert payload["target_bar"]["observed_case_count"] == 0  # type: ignore[index]


def test_reliability_suite_live_mode_uses_pinned_backend(tmp_path: Path) -> None:
    response_sets = [
        [
            json.dumps({"type": "tool_call", "tool": "write_file", "args": {"path": "RESULT.md", "content": "# Result\n\nrecorded edit success\n"}}),
            json.dumps({"type": "final", "content": "Created RESULT.md."}),
        ],
        [
            json.dumps({"type": "tool_call", "tool": "list_files", "args": {"path": "."}}),
            json.dumps({"type": "final", "content": "Inspected fixture files."}),
        ],
        [
            json.dumps({"type": "tool_call", "tool": "write_file", "args": {"path": ".", "content": "bad"}}),
            json.dumps({"type": "tool_call", "tool": "write_file", "args": {"path": "RECOVERED.md", "content": "# Recovered\n\nsecond attempt succeeded\n"}}),
            json.dumps({"type": "final", "content": "Recovered and created RECOVERED.md."}),
        ],
        [
            json.dumps({"type": "tool_call", "tool": "read_file", "args": {"path": "README.md"}}),
        ],
    ]

    class LiveSuiteClient:
        def __init__(self, responses: list[str]) -> None:
            self.responses = list(responses)

        def chat(self, messages, *, json_mode=False, on_delta=None, cancel_event=None):  # noqa: ANN001, ANN201
            response = self.responses.pop(0)
            if on_delta is not None:
                on_delta(response)
            return response

        def list_models(self) -> list[str]:
            return ["live-suite-model"]

        def close(self) -> None:
            return None

        def __enter__(self) -> "LiveSuiteClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def live_suite_factory(_base_url: str, model: str, _timeout: float) -> LiveSuiteClient:
        assert model == "live-suite-model"
        return LiveSuiteClient(response_sets.pop(0))

    register_llm_backend("live_suite_fake", live_suite_factory, source_id="test")

    payload = reliability_suite_payload(
        Settings(workspace=tmp_path),
        run_id="live",
        suite_kind="live",
        backend_override="live_suite_fake",
        model_override="live-suite-model",
    )

    assert payload["schema"] == "agentx.reliability_suite.v1"
    assert payload["ok"] is True
    assert payload["suite_kind"] == "live"
    assert payload["backend"] == "live_suite_fake"
    assert payload["model"] == "live-suite-model"
    assert payload["case_count"] == 4
    assert payload["target_bar"]["profile"] == "live-v1"  # type: ignore[index]
    assert payload["target_bar"]["status"] == "observed"  # type: ignore[index]
    assert payload["target_bar"]["ratification_required"] is False  # type: ignore[index]
    assert payload["target_bar"]["meets_threshold"] is True  # type: ignore[index]
    assert {case["suite_kind"] for case in payload["cases"]} == {"live"}  # type: ignore[index]


def test_reliability_suite_live_mode_blocks_unknown_backend(tmp_path: Path) -> None:
    payload = reliability_suite_payload(
        Settings(workspace=tmp_path),
        run_id="live-missing",
        suite_kind="live",
        backend_override="missing_backend",
        model_override="live-suite-model",
    )

    assert payload["ok"] is False
    assert payload["suite_kind"] == "live"
    assert payload["backend"] == "missing_backend"
    assert payload["blockers"] == ["backend_not_registered"]
    assert payload["case_count"] == 0
    assert payload["target_bar"]["profile"] == "live-v1"  # type: ignore[index]


def test_reliability_decision_requires_valid_evidence(tmp_path: Path) -> None:
    payload = reliability_decision_payload(
        Settings(workspace=tmp_path),
        profile="recorded-v1",
        decision="ratified",
    )

    assert payload["ok"] is False
    assert payload["accepted"] is False
    assert "missing_evidence_source" in payload["blockers"]  # type: ignore[operator]
    assert "decision_requires_valid_evidence" in payload["blockers"]  # type: ignore[operator]


def test_reliability_decision_accepts_matching_suite_evidence(tmp_path: Path) -> None:
    suite = reliability_suite_payload(Settings(workspace=tmp_path), run_id="decision-suite")
    evidence = tmp_path / "suite.json"
    evidence.write_text(json.dumps(suite), encoding="utf-8")

    payload = reliability_decision_payload(
        Settings(workspace=tmp_path),
        profile="recorded-v1",
        decision="ratified",
        evidence_source=str(evidence),
    )

    assert payload["ok"] is True
    assert payload["accepted"] is True
    assert payload["evidence_valid"] is True
    assert payload["evidence"]["profile"] == "recorded-v1"  # type: ignore[index]
    assert payload["write"] is False
    assert payload["wrote"] is False


def test_reliability_decision_cli_writes_artifact(tmp_path: Path) -> None:
    suite = reliability_suite_payload(Settings(workspace=tmp_path), run_id="decision-cli-suite")
    evidence = tmp_path / "suite.json"
    evidence.write_text(json.dumps(suite), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "reliability-decision",
            "--workspace",
            str(tmp_path),
            "--profile",
            "recorded-v1",
            "--decision",
            "ratified",
            "--evidence",
            str(evidence),
            "--write",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.reliability_decision.v1"
    assert payload["ok"] is True
    assert payload["wrote"] is True
    output_path = Path(payload["output_path"])
    assert output_path.is_file()
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["schema"] == "agentx.reliability_decision.v1"
    assert written["accepted"] is True
    assert written["wrote"] is True


def test_reliability_profile_payload_is_read_only_by_default(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTX_BACKEND", "ollama")
    payload = reliability_profile_payload(
        workspace_override=tmp_path,
        model_override="pinned-model",
    )

    assert payload["schema"] == "agentx.reliability_profile.v1"
    assert payload["profile"] == "live-backend"
    assert payload["backend"] == "ollama"
    assert payload["model"] == "pinned-model"
    assert payload["live_probe"] is False
    assert payload["model_available"] is None
    assert payload["backend_registered"] is True
    assert payload["ready_for_live_suite"] is True
    assert payload["recommended_kind"] == "verify_live_profile"
    assert payload["recommended_risk"] == "YELLOW"


def test_reliability_profile_blocks_unknown_backend(tmp_path: Path) -> None:
    payload = reliability_profile_payload(
        workspace_override=tmp_path,
        backend_override="missing_backend",
        model_override="pinned-model",
    )

    assert payload["status"] == "needs_attention"
    assert payload["backend_registered"] is False
    assert payload["blockers"] == ["backend_not_registered"]
    assert payload["ready_for_live_suite"] is False


def test_reliability_profile_live_probe_checks_model(tmp_path: Path) -> None:
    class ProfileClient:
        def __init__(self, _base_url: str, _model: str, _timeout: float) -> None:
            pass

        def chat(self, messages, *, json_mode=False, on_delta=None, cancel_event=None):  # noqa: ANN001, ANN201
            return "{}"

        def list_models(self) -> list[str]:
            return ["pinned-live-model"]

        def close(self) -> None:
            return None

        def __enter__(self) -> "ProfileClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    register_llm_backend("profile_fake", ProfileClient, source_id="test")

    payload = reliability_profile_payload(
        workspace_override=tmp_path,
        backend_override="profile_fake",
        model_override="pinned-live-model",
        live_probe=True,
    )

    assert payload["live_probe"] is True
    assert payload["model_available"] is True
    assert payload["models_count"] == 1
    assert payload["blockers"] == []
    assert payload["ready_for_live_suite"] is True
    assert payload["recommended_kind"] == "run_reliability_suite"


def test_reliability_profile_cli_jsonl_outputs_event(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "reliability-profile",
            "--workspace",
            str(tmp_path),
            "--backend",
            "ollama",
            "--model",
            "pinned-model",
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "reliability_profile"
    assert envelope["data"]["schema"] == "agentx.reliability_profile.v1"
    assert envelope["data"]["model"] == "pinned-model"
