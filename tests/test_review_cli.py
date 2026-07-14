import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, review_exit_code, review_payload
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


def _passing_verify(workspace: Path) -> dict[str, object]:
    return {
        "schema": "agentx.verify.v1",
        "workspace": str(workspace.resolve()),
        "generated_at": "2026-01-02T00:00:00",
        "ok": True,
        "count": 1,
        "checks": [
            {
                "command": "test",
                "argv": ["test"],
                "ok": True,
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "output": "ok",
            }
        ],
    }


def _failing_verify(workspace: Path) -> dict[str, object]:
    payload = _passing_verify(workspace)
    payload["ok"] = False
    payload["checks"][0]["ok"] = False  # type: ignore[index]
    payload["checks"][0]["exit_code"] = 1  # type: ignore[index]
    payload["checks"][0]["output"] = "failed"  # type: ignore[index]
    return payload


def test_review_payload_reports_commit_ready(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: _passing_verify(settings.workspace))

    payload = review_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.review.v1"
    assert payload["ok"] is True
    assert payload["commit_ready"] is True
    assert payload["blockers"] == []
    assert payload["diff"]["schema"] == "agentx.diff.v1"  # type: ignore[index]
    assert payload["diff"]["file_count"] == 1  # type: ignore[index]
    assert payload["verify"]["ok"] is True  # type: ignore[index]
    assert "/commit 中文訊息" in payload["next_commands"]


def test_review_payload_blocks_when_verify_fails(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: _failing_verify(settings.workspace))

    payload = review_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["commit_ready"] is False
    assert payload["blockers"] == ["verify_failed"]
    assert review_exit_code(payload, fail_on_blocker=True) == 1


def test_review_payload_blocks_when_no_changes(tmp_path: Path, monkeypatch) -> None:
    _git(tmp_path, ["init"])
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: _passing_verify(settings.workspace))

    payload = review_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["commit_ready"] is False
    assert "no_changes" in payload["blockers"]


def test_review_payload_skip_verify_warns(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    payload = review_payload(Settings(workspace=tmp_path), run_verify=False)

    assert payload["ok"] is True
    assert payload["commit_ready"] is False
    assert payload["verify"] is None
    assert payload["warnings"] == ["verify_skipped"]
    assert "agentx verify --json --fail-on-error" in payload["next_commands"]
    assert "/commit 中文訊息" not in payload["next_commands"]


def test_review_json_outputs_payload(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: _passing_verify(settings.workspace))

    result = CliRunner().invoke(app, ["review", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.review.v1"
    assert payload["commit_ready"] is True
    assert payload["diff"]["file_count"] == 1


def test_review_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["review", "--workspace", str(tmp_path), "--skip-verify", "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "review"
    assert envelope["data"]["schema"] == "agentx.review.v1"
    assert envelope["data"]["warnings"] == ["verify_skipped"]


def test_review_fail_on_blocker_exits_one_but_prints_payload(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: _failing_verify(settings.workspace))

    result = CliRunner().invoke(
        app,
        ["review", "--workspace", str(tmp_path), "--json", "--fail-on-blocker"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.review.v1"
    assert payload["blockers"] == ["verify_failed"]


def test_review_plain_outputs_gate_summary(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(app, ["review", "--workspace", str(tmp_path), "--skip-verify"])

    assert result.exit_code == 0, result.output
    assert "agentX review gate" in result.output
    assert "commit_ready" in result.output
    assert "verify_skipped" in result.output
