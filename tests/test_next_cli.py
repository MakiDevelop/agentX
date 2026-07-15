import json
import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, next_payload
from agentx.config import Settings
from agentx.tasks import save_tasks


def _git(path: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_repo(path: Path) -> Path:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "test@example.com"])
    _git(path, ["config", "user.name", "Test User"])
    (path / ".gitignore").write_text(".agentx/\n", encoding="utf-8")
    target = path / "note.txt"
    target.write_text("one\n", encoding="utf-8")
    _git(path, ["add", ".gitignore", "note.txt"])
    _git(path, ["commit", "-m", "init"])
    return target


def _write_denied_session(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                '{"ts":"2026-01-02T00:00:00","event":"session_start"}',
                '{"ts":"2026-01-02T00:00:01","event":"approval","tool":"apply_patch","allowed":false}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_artifact_bundle(root: Path, name: str, *, needs_handoff: bool = True, mtime: int = 1) -> Path:
    bundle = root / name
    bundle.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "agentx.headless_result.v1",
        "termination": "max_steps_exceeded" if needs_handoff else "completed",
        "exit_code": 1 if needs_handoff else 0,
        "log_summary": {
            "handoff_summary": {
                "needs_handoff": needs_handoff,
                "resume_command": "agentx -p '<next prompt>' --agent --json",
            }
        },
    }
    (bundle / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (bundle / "handoff.md").write_text("# Handoff\n", encoding="utf-8")
    for item in bundle.iterdir():
        os.utime(item, (mtime, mtime))
    return bundle


def _write_workflow_run_artifact(root: Path, name: str, *, ok: bool = False, mtime: int = 10) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    payload = {
        "schema": "agentx.workflow_run.v1",
        "query": "memory",
        "ok": ok,
        "execute": False,
        "stopped_at": {"reason": "missing_inputs"} if not ok else None,
        "blockers": ["missing_inputs"] if not ok else [],
        "approval_receipts": [],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.utime(target, (mtime, mtime))
    return target


def test_next_payload_recommends_gate_for_dirty_workspace(tmp_path: Path) -> None:
    target = _git_repo(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.next.v1"
    assert payload["signals"]["dirty"] is True  # type: ignore[index]
    assert payload["recommended_command"] == "agentx gate --json --fail-on-blocker"
    assert payload["recommended_kind"] == "gate"
    assert payload["recommended_risk"] == "GREEN"
    assert payload["recommendations"][0]["kind"] == "gate"  # type: ignore[index]
    assert payload["recommendations"][1]["kind"] == "commit_plan"  # type: ignore[index]
    recommendation_kinds = [item["kind"] for item in payload["recommendations"]]  # type: ignore[index]
    assert "memory_handoff_workflow" in recommendation_kinds
    assert "ace_council_workflow" in recommendation_kinds
    assert payload["recommendations"][0]["command_plan"]["schema"] == "agentx.command_plan.v1"  # type: ignore[index]
    assert payload["recommendations"][0]["command_plan"]["allowed"] is True  # type: ignore[index]


def test_next_payload_prioritizes_denied_approval(tmp_path: Path) -> None:
    target = _git_repo(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")
    _write_denied_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["denied_approval_count"] == 1  # type: ignore[index]
    assert payload["recommendations"][0]["kind"] == "approval_audit"  # type: ignore[index]
    assert payload["recommended_command"] == "agentx approvals latest --denied --json --fail-on-denied"
    assert payload["recommended_kind"] == "approval_audit"


def test_next_payload_recommends_handoff_resume_for_latest_artifact(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _write_artifact_bundle(tmp_path / ".agentx" / "runs", "latest", needs_handoff=True)

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["latest_artifact_needs_handoff"] is True  # type: ignore[index]
    assert payload["recommendations"][0]["kind"] == "handoff_resume"  # type: ignore[index]
    assert payload["recommended_command"] == "agentx handoff-resume .agentx/runs/latest --dry-run"
    assert payload["recommended_kind"] == "handoff_resume"


def test_next_payload_recommends_latest_workflow_run_artifact_when_clean(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _write_workflow_run_artifact(tmp_path / ".agentx" / "runs", "workflow-memory.json", ok=False)

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["latest_artifact_type"] == "workflow_run"  # type: ignore[index]
    assert payload["signals"]["latest_workflow_run_query"] == "memory"  # type: ignore[index]
    assert payload["signals"]["latest_workflow_run_ok"] is False  # type: ignore[index]
    assert payload["signals"]["latest_workflow_run_stopped"] is True  # type: ignore[index]
    assert payload["signals"]["latest_workflow_resume_ready"] is True  # type: ignore[index]
    assert payload["signals"]["latest_workflow_missing_input_count"] == 0  # type: ignore[index]
    assert payload["recommendations"][0]["kind"] == "workflow_artifact_inspect"  # type: ignore[index]
    assert payload["recommendations"][0]["command"] == "agentx workflow-inspect .agentx/runs/workflow-memory.json --json"  # type: ignore[index]
    assert payload["recommended_kind"] == "workflow_artifact_inspect"
    assert payload["recommended_risk"] == "GREEN"


def test_next_payload_recommends_workflow_resume_for_ready_artifact(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _write_workflow_run_artifact(tmp_path / ".agentx" / "runs", "workflow-memory.json", ok=True)

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["latest_artifact_type"] == "workflow_run"  # type: ignore[index]
    assert payload["signals"]["latest_workflow_run_ok"] is True  # type: ignore[index]
    assert payload["signals"]["latest_workflow_run_stopped"] is False  # type: ignore[index]
    assert payload["signals"]["latest_workflow_resume_ready"] is True  # type: ignore[index]
    assert payload["recommendations"][0]["kind"] == "workflow_resume"  # type: ignore[index]
    assert payload["recommendations"][0]["command"] == "agentx workflow-resume .agentx/runs/workflow-memory.json --result-output auto --dry-run --json"  # type: ignore[index]
    assert payload["recommendations"][0]["command_plan"]["risk"] == "GREEN"  # type: ignore[index]
    assert payload["recommended_kind"] == "workflow_resume"


def test_next_payload_recommends_active_tasks_when_clean(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    save_tasks(
        tmp_path,
        [
            {"id": 1, "description": "continue", "status": "in_progress", "notes": ""},
            {"id": 2, "description": "next", "status": "pending", "notes": ""},
        ],
    )

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["active_task_count"] == 2  # type: ignore[index]
    assert payload["signals"]["active_task_ids"] == [1, 2]  # type: ignore[index]
    assert payload["signals"]["primary_active_task"] == {  # type: ignore[index]
        "id": 1,
        "description": "continue",
        "status": "in_progress",
        "notes": "",
    }
    assert payload["recommendations"][0]["kind"] == "task_resume"  # type: ignore[index]
    assert payload["recommendations"][1]["kind"] == "headless_continue"  # type: ignore[index]
    assert payload["recommendations"][-2]["kind"] == "memory_handoff_workflow"  # type: ignore[index]
    assert payload["recommendations"][-1]["kind"] == "ace_council_workflow"  # type: ignore[index]
    assert "primary=#1: in_progress: continue" in payload["recommendations"][0]["reason"]  # type: ignore[index]


def test_next_payload_defaults_to_inspect_when_idle(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    payload = next_payload(Settings(workspace=tmp_path))

    assert payload["signals"]["dirty"] is False  # type: ignore[index]
    assert payload["signals"]["active_task_count"] == 0  # type: ignore[index]
    assert payload["recommendations"][0]["rank"] == 1  # type: ignore[index]
    assert payload["recommendations"][0]["kind"] == "inspect"  # type: ignore[index]
    assert payload["recommendations"][0]["command"] == "agentx inspect --json"  # type: ignore[index]
    assert payload["recommendations"][1]["kind"] == "memory_handoff_workflow"  # type: ignore[index]
    assert payload["recommendations"][1]["command"] == "agentx workflow-run memory --json"  # type: ignore[index]
    assert payload["recommendations"][1]["command_plan"]["schema"] == "agentx.command_plan.v1"  # type: ignore[index]
    assert payload["recommendations"][2]["kind"] == "ace_council_workflow"  # type: ignore[index]
    assert payload["recommendations"][2]["command"] == "agentx workflow-run ace --json"  # type: ignore[index]
    assert payload["signals"]["workflow_recommendation_count"] == 2  # type: ignore[index]
    assert payload["recommended_kind"] == "inspect"
    assert payload["recommended_risk"] == "GREEN"
    assert payload["recommendations"][0]["reason"] == "workspace is clean and no active runner handoff was detected"  # type: ignore[index]
    assert payload["recommendations"][0]["risk"] == "GREEN"  # type: ignore[index]
    assert payload["recommendations"][0]["command_plan"]["schema"] == "agentx.command_plan.v1"  # type: ignore[index]


def test_next_json_outputs_payload(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    result = CliRunner().invoke(app, ["next", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.next.v1"
    assert payload["recommended_command"] == "agentx inspect --json"


def test_next_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    result = CliRunner().invoke(app, ["next", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "next"
    assert envelope["data"]["schema"] == "agentx.next.v1"


def test_next_plain_outputs_recommendations(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    result = CliRunner().invoke(app, ["next", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX next" in result.output
    assert "agentx inspect --json" in result.output
