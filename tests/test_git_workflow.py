from pathlib import Path

import pytest

from agentx.git_workflow import (
    GitPathError,
    parse_status_files,
    push_current_branch,
    stage_paths,
    unstage_paths,
)


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


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


def test_push_current_branch_requires_existing_upstream(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    output = push_current_branch(tmp_path)

    assert "push aborted" in output
    assert "no upstream" in output
    assert "$ git push" not in output


def test_push_current_branch_uses_plain_git_push_with_upstream(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    local.mkdir()
    _git(remote.parent, "init", "--bare", remote.name)
    _init_repo(local)
    _git(local, "remote", "add", "origin", str(remote))
    _git(local, "push", "-u", "origin", "HEAD")

    target = local / "README.md"
    target.write_text("hello\n", encoding="utf-8")
    _git(local, "add", "--", "README.md")
    _git(local, "commit", "-m", "add readme")

    output = push_current_branch(local)

    assert "$ git push" in output
    assert "git push -u" not in output
    assert "exit=0" in output


def test_git_readonly_tools_show_branch_log_and_revision(tmp_path: Path) -> None:
    from agentx.tools import ToolRegistry, builtin_tools

    _init_repo(tmp_path)
    (tmp_path / "feature.py").write_text("print('feature')\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "feature.py")
    _git(tmp_path, "commit", "-m", "add feature")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    branch = registry.run("git_branch", {})
    assert branch.ok
    assert "*" in branch.content

    log = registry.run("git_log", {"limit": 1})
    assert log.ok
    assert "add feature" in log.content
    assert "init" not in log.content

    shown = registry.run("git_show", {"rev": "HEAD"})
    assert shown.ok
    assert "add feature" in shown.content
    assert "feature.py" in shown.content

    rejected = registry.run("git_show", {"rev": "--hard"})
    assert not rejected.ok
    assert "unsupported git revision" in rejected.content


def test_git_push_tool_is_registered_and_requires_upstream(tmp_path: Path) -> None:
    from agentx.tools import ToolRegistry, builtin_tools

    _init_repo(tmp_path)
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("git_push", {})

    assert not result.ok
    assert "push aborted" in result.content
    assert "$ git push" not in result.content
