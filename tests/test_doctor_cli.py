import json
import subprocess

from typer.testing import CliRunner

from agentx.cli import app, doctor_exit_code, doctor_payload_from_checks
from agentx.config import Settings


def _git_init(path) -> None:  # noqa: ANN001
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def _write_workflow_artifact(path) -> None:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "agentx.workflow_run.v1",
                "query": "memory",
                "ok": False,
                "execute": False,
                "stopped_at": {"reason": "side_effect_gate"},
                "blockers": ["missing_inputs"],
                "approval_receipts": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_doctor_payload_from_checks_aggregates_ok(tmp_path) -> None:  # noqa: ANN001
    settings = Settings(workspace=tmp_path)

    payload = doctor_payload_from_checks(
        [
            ("uv", True, "uv 0.1"),
            ("git", False, "not a git repository"),
        ],
        settings=settings,
        live_probes=False,
    )

    assert payload["schema"] == "agentx.doctor.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["live_probes"] is False
    assert payload["ok"] is False
    assert payload["warnings"] == []
    assert payload["workflow_artifact_health"]["status"] == "no_workflow_artifact"  # type: ignore[index]
    assert payload["checks"] == [
        {"name": "uv", "ok": True, "detail": "uv 0.1"},
        {"name": "git", "ok": False, "detail": "not a git repository"},
    ]


def test_doctor_exit_code_is_opt_in(tmp_path) -> None:  # noqa: ANN001
    payload = doctor_payload_from_checks(
        [("git", False, "not a git repository")],
        settings=Settings(workspace=tmp_path),
        live_probes=False,
    )

    assert doctor_exit_code(payload, fail_on_error=False) == 0
    assert doctor_exit_code(payload, fail_on_error=True) == 1


def test_doctor_static_json_outputs_local_checks(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)

    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.doctor.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["live_probes"] is False
    assert payload["ok"] is True
    assert payload["workflow_artifact_health"]["schema"] == "agentx.workflow_artifact_health.v1"
    assert payload["workflow_artifact_health"]["status"] == "no_workflow_artifact"
    names = {check["name"] for check in payload["checks"]}
    assert names == {"uv", "git", "task_migration (MT22)"}


def test_doctor_static_warns_for_workflow_artifact_needing_inspect(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)
    _write_workflow_artifact(tmp_path / ".agentx" / "runs" / "workflow-memory.json")

    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["warnings"] == ["workflow_artifact_needs_inspect"]
    assert payload["workflow_artifact_health"]["status"] == "needs_inspect"
    assert payload["workflow_artifact_health"]["latest_artifact"] == ".agentx/runs/workflow-memory.json"
    assert payload["workflow_artifact_health"]["recommended_command"] == "agentx workflow-inspect .agentx/runs/workflow-memory.json --json"


def test_doctor_static_fail_on_error_exits_one_but_prints_payload(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        ["doctor", "--workspace", str(tmp_path), "--static", "--json", "--fail-on-error"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.doctor.v1"
    assert payload["ok"] is False
    git_check = next(check for check in payload["checks"] if check["name"] == "git")
    assert git_check["ok"] is False


def test_doctor_static_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "doctor"
    assert envelope["data"]["schema"] == "agentx.doctor.v1"
    assert envelope["data"]["live_probes"] is False


def test_doctor_static_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static"])

    assert result.exit_code == 0, result.output
    assert "agentX doctor" in result.output
    assert "uv" in result.output
    assert "git" in result.output
