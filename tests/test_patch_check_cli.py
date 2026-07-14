import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, patch_check_exit_code, patch_check_payload
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


def _valid_patch() -> str:
    return "\n".join(
        [
            "diff --git a/note.txt b/note.txt",
            "--- a/note.txt",
            "+++ b/note.txt",
            "@@ -1 +1,2 @@",
            " one",
            "+two",
            "",
        ]
    )


def test_patch_check_payload_reports_valid_patch(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    patch = tmp_path / "fix.patch"
    patch.write_text(_valid_patch(), encoding="utf-8")

    payload = patch_check_payload(Settings(workspace=tmp_path), patch_file="fix.patch")

    assert payload["schema"] == "agentx.patch_check.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["patch_file"] == "fix.patch"
    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["apply_check"]["ok"] is True  # type: ignore[index]
    assert payload["safe_paths_ok"] is True
    assert payload["file_count"] == 1
    assert payload["files"][0]["path"] == "note.txt"  # type: ignore[index]
    assert payload["files"][0]["safe"] is True  # type: ignore[index]
    assert payload["files"][0]["added"] == 1  # type: ignore[index]
    assert "/apply fix.patch" in payload["next_commands"]


def test_patch_check_payload_blocks_workspace_escape_patch_file(tmp_path: Path) -> None:
    payload = patch_check_payload(Settings(workspace=tmp_path), patch_file="../outside.patch")

    assert payload["ok"] is False
    assert payload["blockers"] == ["patch_file_escapes_workspace"]
    assert patch_check_exit_code(payload, fail_on_blocker=True) == 1


def test_patch_check_payload_blocks_missing_patch_file(tmp_path: Path) -> None:
    payload = patch_check_payload(Settings(workspace=tmp_path), patch_file="missing.patch")

    assert payload["ok"] is False
    assert payload["blockers"] == ["patch_file_not_found"]


def test_patch_check_payload_blocks_malformed_patch(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    patch = tmp_path / "bad.patch"
    patch.write_text("not a patch\n", encoding="utf-8")

    payload = patch_check_payload(Settings(workspace=tmp_path), patch_file="bad.patch")

    assert payload["ok"] is False
    assert "git_apply_check_failed" in payload["blockers"]
    assert payload["apply_check"]["ok"] is False  # type: ignore[index]


def test_patch_check_payload_blocks_protected_patch_target(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    protected = tmp_path / "protected.patch"
    protected.write_text(
        "\n".join(
            [
                "diff --git a/.agentx/state.json b/.agentx/state.json",
                "--- a/.agentx/state.json",
                "+++ b/.agentx/state.json",
                "@@ -0,0 +1 @@",
                '+{"x":1}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    payload = patch_check_payload(Settings(workspace=tmp_path), patch_file="protected.patch")

    assert payload["ok"] is False
    assert "unsafe_patch_paths" in payload["blockers"]
    assert any(item["path"] == ".agentx/state.json" and item["safe"] is False for item in payload["files"])  # type: ignore[index]


def test_patch_check_json_outputs_payload(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    (tmp_path / "fix.patch").write_text(_valid_patch(), encoding="utf-8")

    result = CliRunner().invoke(app, ["patch-check", "fix.patch", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.patch_check.v1"
    assert payload["ok"] is True
    assert payload["files"][0]["path"] == "note.txt"


def test_patch_check_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    (tmp_path / "fix.patch").write_text(_valid_patch(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["patch-check", "fix.patch", "--workspace", str(tmp_path), "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "patch_check"
    assert envelope["data"]["schema"] == "agentx.patch_check.v1"


def test_patch_check_fail_on_blocker_exits_one_but_prints_payload(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["patch-check", "missing.patch", "--workspace", str(tmp_path), "--json", "--fail-on-blocker"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.patch_check.v1"
    assert payload["blockers"] == ["patch_file_not_found"]


def test_patch_check_plain_outputs_summary(tmp_path: Path) -> None:
    _git_repo_with_file(tmp_path)
    (tmp_path / "fix.patch").write_text(_valid_patch(), encoding="utf-8")

    result = CliRunner().invoke(app, ["patch-check", "fix.patch", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX patch check" in result.output
    assert "note.txt" in result.output
