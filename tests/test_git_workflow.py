from pathlib import Path

import pytest

from agentx.git_workflow import GitPathError, parse_status_files, stage_paths, unstage_paths


def _git(repo: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".gitkeep").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "--", ".gitkeep")
    _git(repo, "commit", "-m", "init")


def test_parse_status_files() -> None:
    status = """## main...origin/main
 M README.md
?? src/new.py
D  old.txt
R  a.txt -> b.txt
"""
    assert parse_status_files(status) == ["README.md", "src/new.py", "old.txt", "a.txt", "b.txt"]


def test_stage_and_unstage_single_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "README.md"
    target.write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "README.md")
    _git(tmp_path, "commit", "-m", "add readme")
    target.write_text("hello changed\n", encoding="utf-8")

    stage_output = stage_paths(tmp_path, ["README.md"])

    assert "$ git add -- README.md" in stage_output
    assert _git(tmp_path, "status", "--short") == "M  README.md\n"

    unstage_output = unstage_paths(tmp_path, ["README.md"])

    assert "$ git restore --staged -- README.md" in unstage_output
    assert _git(tmp_path, "status", "--short") == " M README.md\n"
    assert target.read_text(encoding="utf-8") == "hello changed\n"


@pytest.mark.parametrize("bad_path", ["", ".", "./", "*", "*.py", "--all", "src/[abc].py"])
def test_stage_rejects_broad_or_option_like_paths(tmp_path: Path, bad_path: str) -> None:
    _init_repo(tmp_path)
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")

    with pytest.raises(GitPathError):
        stage_paths(tmp_path, [bad_path])

    assert _git(tmp_path, "status", "--short") == "?? safe.py\n"


def test_stage_rejects_workspace_escape_and_directories(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "safe.py").write_text("print('safe')\n", encoding="utf-8")

    with pytest.raises(GitPathError, match="escapes workspace"):
        stage_paths(tmp_path, ["../outside.py"])

    with pytest.raises(GitPathError, match="directory path"):
        stage_paths(tmp_path, ["src"])

    assert _git(tmp_path, "status", "--short") == "?? src/\n"


def test_stage_validates_all_paths_before_staging(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")

    with pytest.raises(GitPathError):
        stage_paths(tmp_path, ["safe.py", "."])

    assert _git(tmp_path, "status", "--short") == "?? safe.py\n"
