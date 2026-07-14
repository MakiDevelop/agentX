import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentx.cli import app, diff_payload
from agentx.config import Settings


def _git(path: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_repo_with_file(path: Path) -> Path:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "test@example.com"])
    _git(path, ["config", "user.name", "Test User"])
    target = path / "note.txt"
    target.write_text("one\n", encoding="utf-8")
    _git(path, ["add", "note.txt"])
    _git(path, ["commit", "-m", "init"])
    return target


def test_diff_payload_reports_worktree_diff(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")

    payload = diff_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.diff.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["ok"] is True
    assert payload["is_git_repo"] is True
    assert payload["dirty"] is True
    assert payload["file_count"] == 1
    assert payload["insertions"] == 1
    assert payload["deletions"] == 0
    assert payload["files"] == [
        {
            "status": "M",
            "path": "note.txt",
            "added": 1,
            "deleted": 0,
            "binary": False,
        }
    ]
    assert "note.txt" in payload["stat"]
    assert payload["patch"] is None


def test_diff_payload_reports_staged_diff(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")
    _git(tmp_path, ["add", "note.txt"])

    payload = diff_payload(Settings(workspace=tmp_path), staged=True)

    assert payload["ok"] is True
    assert payload["staged"] is True
    assert payload["file_count"] == 1
    assert payload["files"][0]["path"] == "note.txt"  # type: ignore[index]


def test_diff_payload_includes_untracked_files(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")

    payload = diff_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is True
    assert payload["dirty"] is True
    assert payload["file_count"] == 1
    assert payload["untracked_count"] == 1
    assert payload["files"] == [
        {
            "status": "??",
            "path": "new.txt",
            "added": None,
            "deleted": None,
            "binary": False,
        }
    ]


def test_diff_payload_can_include_truncated_patch(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    payload = diff_payload(Settings(workspace=tmp_path), include_patch=True, max_patch_chars=20)

    assert payload["ok"] is True
    assert payload["patch_included"] is True
    assert isinstance(payload["patch"], str)
    assert len(payload["patch"]) == 20
    assert payload["patch_truncated"] is True


def test_diff_payload_handles_non_git_workspace(tmp_path: Path) -> None:
    payload = diff_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["is_git_repo"] is False
    assert payload["dirty"] is None
    assert payload["files"] == []
    assert payload["detail"]


def test_diff_payload_rejects_workspace_escape(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)

    with pytest.raises(ValueError, match="Path escapes workspace"):
        diff_payload(Settings(workspace=tmp_path), path="../outside.txt")


def test_diff_json_outputs_payload(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["diff", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.diff.v1"
    assert payload["file_count"] == 1
    assert payload["files"][0]["path"] == "note.txt"


def test_diff_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["diff", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "diff"
    assert envelope["data"]["schema"] == "agentx.diff.v1"
    assert envelope["data"]["file_count"] == 1


def test_diff_plain_outputs_table(tmp_path: Path) -> None:
    target = _git_repo_with_file(tmp_path)
    target.write_text("one\ntwo\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["diff", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX diff" in result.output
    assert "note.txt" in result.output
    assert "insertions=1" in result.output
    assert "untracked=0" in result.output
