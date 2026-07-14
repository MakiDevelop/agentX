import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, commit_plan_exit_code, commit_plan_payload
from agentx.config import Settings


def _git(path: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_repo_with_change(path: Path) -> None:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "test@example.com"])
    _git(path, ["config", "user.name", "Test User"])
    target = path / "note.txt"
    target.write_text("one\n", encoding="utf-8")
    _git(path, ["add", "note.txt"])
    _git(path, ["commit", "-m", "init"])
    target.write_text("one\ntwo\n", encoding="utf-8")


def _passing_review(workspace: Path) -> dict[str, object]:
    return {
        "schema": "agentx.review.v1",
        "workspace": str(workspace.resolve()),
        "generated_at": "2026-01-02T00:00:00",
        "ok": True,
        "commit_ready": True,
        "blockers": [],
        "warnings": [],
        "diff": {"schema": "agentx.diff.v1", "dirty": True},
        "verify": {"schema": "agentx.verify.v1", "ok": True},
        "next_commands": ["agentx diff --json", "/commit message"],
    }


def _failing_review(workspace: Path) -> dict[str, object]:
    payload = _passing_review(workspace)
    payload["ok"] = False
    payload["commit_ready"] = False
    payload["blockers"] = ["verify_failed"]
    return payload


def test_commit_plan_payload_reports_ready_with_message(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _passing_review(settings.workspace))

    payload = commit_plan_payload(Settings(workspace=tmp_path), message="新增功能")

    assert payload["schema"] == "agentx.commit_plan.v1"
    assert payload["ok"] is True
    assert payload["ready_to_commit"] is True
    assert payload["commit_message"] == "新增功能"
    assert payload["files_to_stage"] == ["note.txt"]
    assert payload["file_count"] == 1
    assert payload["blockers"] == []
    assert "/commit 新增功能" in payload["next_commands"]


def test_commit_plan_payload_blocks_without_message(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _passing_review(settings.workspace))

    payload = commit_plan_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["ready_to_commit"] is False
    assert payload["commit_message"] is None
    assert payload["blockers"] == ["missing_commit_message"]
    assert commit_plan_exit_code(payload, fail_on_blocker=True) == 1


def test_commit_plan_payload_carries_review_blockers(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _failing_review(settings.workspace))

    payload = commit_plan_payload(Settings(workspace=tmp_path), message="修正測試")

    assert payload["ok"] is False
    assert payload["ready_to_commit"] is False
    assert payload["blockers"] == ["verify_failed"]


def test_commit_plan_json_outputs_payload(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _passing_review(settings.workspace))

    result = CliRunner().invoke(
        app,
        ["commit-plan", "--workspace", str(tmp_path), "--message", "新增功能", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.commit_plan.v1"
    assert payload["ready_to_commit"] is True
    assert payload["files_to_stage"] == ["note.txt"]


def test_commit_plan_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["commit-plan", "--workspace", str(tmp_path), "-m", "新增功能", "--skip-verify", "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "commit_plan"
    assert envelope["data"]["schema"] == "agentx.commit_plan.v1"
    assert envelope["data"]["commit_message"] == "新增功能"
    assert envelope["data"]["ready_to_commit"] is False
    assert "agentx review --json --fail-on-blocker" in envelope["data"]["next_commands"]


def test_commit_plan_fail_on_blocker_exits_one_but_prints_payload(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["commit-plan", "--workspace", str(tmp_path), "--json", "--fail-on-blocker"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.commit_plan.v1"
    assert "missing_commit_message" in payload["blockers"]


def test_commit_plan_plain_outputs_plan(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["commit-plan", "--workspace", str(tmp_path), "-m", "新增功能", "--skip-verify"],
    )

    assert result.exit_code == 0, result.output
    assert "agentX commit plan" in result.output
    assert "ready_to_commit" in result.output
    assert "note.txt" in result.output
