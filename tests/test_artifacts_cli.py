import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentx.cli import app, artifacts_payload
from agentx.config import Settings


def _result_payload(*, exit_code: int = 0, termination: str = "completed") -> dict[str, object]:
    return {
        "schema_version": "agentx.headless_result.v1",
        "termination": termination,
        "exit_code": exit_code,
        "log_summary": {
            "handoff_summary": {
                "needs_handoff": exit_code != 0,
                "resume_command": "agentx -p '<next prompt>' --agent --json",
            }
        },
    }


def _write_bundle(root: Path, name: str, *, fmt: str = "json", exit_code: int = 0, mtime: int = 1) -> Path:
    bundle = root / name
    bundle.mkdir(parents=True, exist_ok=True)
    payload = _result_payload(exit_code=exit_code, termination="completed" if exit_code == 0 else "max_steps_exceeded")
    if fmt == "jsonl":
        (bundle / "result.jsonl").write_text(
            json.dumps({"event": "result", "data": payload}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        (bundle / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (bundle / "session.session.jsonl").write_text('{"event":"session_start"}\n', encoding="utf-8")
    (bundle / "handoff.md").write_text("# Handoff\n", encoding="utf-8")
    for path in bundle.iterdir():
        os.utime(path, (mtime, mtime))
    return bundle


def _write_workflow_run_artifact(root: Path, name: str, *, ok: bool = False, mtime: int = 30) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    payload = {
        "schema": "agentx.workflow_run.v1",
        "query": "memory",
        "ok": ok,
        "execute": False,
        "stopped_at": {"reason": "side_effect_gate"} if not ok else None,
        "blockers": [] if ok else ["missing_inputs"],
        "approval_receipts": [],
    }
    if target.suffix == ".jsonl":
        target.write_text(
            json.dumps({"event": "workflow_run", "data": payload}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.utime(target, (mtime, mtime))
    return target


def test_artifacts_payload_lists_bundles_sorted_by_mtime(tmp_path: Path) -> None:
    runs = tmp_path / ".agentx" / "runs"
    _write_bundle(runs, "old", exit_code=0, mtime=10)
    _write_bundle(runs, "new", fmt="jsonl", exit_code=1, mtime=20)

    payload = artifacts_payload(Settings(workspace=tmp_path), limit=10)

    assert payload["schema"] == "agentx.artifacts.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["root_relative_path"] == ".agentx/runs"
    assert payload["count"] == 2
    artifacts = payload["artifacts"]
    assert artifacts[0]["name"] == "new"  # type: ignore[index]
    assert artifacts[0]["result_format"] == "jsonl"  # type: ignore[index]
    assert artifacts[0]["exit_code"] == 1  # type: ignore[index]
    assert artifacts[0]["termination"] == "max_steps_exceeded"  # type: ignore[index]
    assert artifacts[0]["needs_handoff"] is True  # type: ignore[index]
    assert artifacts[0]["has_session"] is True  # type: ignore[index]
    assert artifacts[0]["has_handoff"] is True  # type: ignore[index]
    assert payload["latest_artifact"]["name"] == "new"  # type: ignore[index]
    assert payload["recommended_command"] == "agentx handoff-resume .agentx/runs/new --dry-run"
    assert payload["recommended_kind"] == "handoff_resume"
    assert payload["recommended_risk"] == "GREEN"


def test_artifacts_payload_lists_workflow_run_artifacts(tmp_path: Path) -> None:
    runs = tmp_path / ".agentx" / "runs"
    _write_bundle(runs, "old", exit_code=0, mtime=10)
    target = _write_workflow_run_artifact(runs, "workflow-memory.jsonl", ok=False, mtime=30)

    payload = artifacts_payload(Settings(workspace=tmp_path), limit=10)

    assert payload["count"] == 2
    artifact = payload["artifacts"][0]  # type: ignore[index]
    assert artifact["artifact_type"] == "workflow_run"
    assert artifact["name"] == "workflow-memory.jsonl"
    assert artifact["relative_path"] == ".agentx/runs/workflow-memory.jsonl"
    assert artifact["result_relative_path"] == ".agentx/runs/workflow-memory.jsonl"
    assert artifact["result_format"] == "jsonl"
    assert artifact["schema"] == "agentx.workflow_run.v1"
    assert artifact["workflow_query"] == "memory"
    assert artifact["workflow_ok"] is False
    assert artifact["workflow_execute"] is False
    assert artifact["workflow_stopped_at"] == {"reason": "side_effect_gate"}
    assert artifact["workflow_blockers"] == ["missing_inputs"]
    assert artifact["approval_receipt_count"] == 0
    assert artifact["has_session"] is False
    assert artifact["has_handoff"] is False
    assert payload["latest_artifact"]["path"] == str(target)  # type: ignore[index]
    assert payload["recommended_command"] == "agentx artifacts .agentx/runs/workflow-memory.jsonl --json"
    assert payload["recommended_kind"] == "inspect_artifact"


def test_artifacts_payload_accepts_single_workflow_run_file(tmp_path: Path) -> None:
    target = _write_workflow_run_artifact(tmp_path / ".agentx" / "runs", "workflow-memory.json")

    payload = artifacts_payload(Settings(workspace=tmp_path), root=".agentx/runs/workflow-memory.json")

    assert payload["count"] == 1
    assert payload["latest_artifact"]["artifact_type"] == "workflow_run"  # type: ignore[index]
    assert payload["latest_artifact"]["relative_path"] == ".agentx/runs/workflow-memory.json"  # type: ignore[index]
    assert payload["latest_artifact"]["path"] == str(target)  # type: ignore[index]


def test_artifacts_payload_accepts_single_bundle_dir(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / ".agentx" / "runs", "latest")

    payload = artifacts_payload(Settings(workspace=tmp_path), root=".agentx/runs/latest")

    assert payload["count"] == 1
    assert payload["artifacts"][0]["relative_path"] == ".agentx/runs/latest"  # type: ignore[index]
    assert payload["artifacts"][0]["result_relative_path"] == ".agentx/runs/latest/result.json"  # type: ignore[index]
    assert str(bundle) == payload["artifacts"][0]["path"]  # type: ignore[index]
    assert payload["latest_artifact"]["relative_path"] == ".agentx/runs/latest"  # type: ignore[index]
    assert payload["recommended_command"] == "agentx artifacts .agentx/runs/latest --json"
    assert payload["recommended_kind"] == "inspect_artifact"


def test_artifacts_payload_missing_root_is_ok_with_empty_count(tmp_path: Path) -> None:
    payload = artifacts_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["latest_artifact"] is None
    assert payload["recommended_command"] == "agentx -p '任務' --agent --artifact-dir .agentx/runs/latest --quiet"
    assert payload["recommended_kind"] == "headless_bundle"
    assert payload["recommended_risk"] == "YELLOW"
    assert payload["artifacts"] == []
    assert "not found" in payload["detail"]


def test_artifacts_payload_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="escapes workspace"):
        artifacts_payload(Settings(workspace=tmp_path), root="../outside")


def test_artifacts_json_outputs_catalog(tmp_path: Path) -> None:
    _write_bundle(tmp_path / ".agentx" / "runs", "latest", exit_code=1)

    result = CliRunner().invoke(app, ["artifacts", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.artifacts.v1"
    assert payload["count"] == 1
    assert payload["artifacts"][0]["name"] == "latest"
    assert payload["artifacts"][0]["resume_command"] == "agentx -p '<next prompt>' --agent --json"


def test_artifacts_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _write_bundle(tmp_path / ".agentx" / "runs", "latest")

    result = CliRunner().invoke(app, ["artifacts", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "artifacts"
    assert envelope["data"]["schema"] == "agentx.artifacts.v1"


def test_artifacts_plain_outputs_table(tmp_path: Path) -> None:
    _write_bundle(tmp_path / ".agentx" / "runs", "latest")

    result = CliRunner().invoke(app, ["artifacts", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX artifacts" in result.output
    assert "latest" in result.output
    assert "json" in result.output
