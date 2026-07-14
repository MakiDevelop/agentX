from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitCommitPlan:
    status: str
    diff_stat: str
    files: list[str]


class GitPathError(ValueError):
    """Raised when a git path operation would be too broad or unsafe."""


class GitPushError(ValueError):
    """Raised when a git push operation is outside the supported safe path."""


def build_commit_plan(workspace: Path) -> GitCommitPlan:
    status = _git(workspace, ["status", "--short", "--branch"]).stdout
    diff_stat = _git(workspace, ["diff", "--stat"]).stdout
    files = parse_status_files(status)
    return GitCommitPlan(status=status, diff_stat=diff_stat, files=files)


def parse_status_files(status: str) -> list[str]:
    files: list[str] = []
    for line in status.splitlines():
        if not line or line.startswith("## "):
            continue
        path_part = line[3:]
        if " -> " in path_part:
            old_path, new_path = path_part.split(" -> ", 1)
            files.extend([old_path, new_path])
        else:
            files.append(path_part)
    return [path for path in dict.fromkeys(files) if path]


def commit_and_push(workspace: Path, files: list[str], message: str) -> str:
    outputs = []
    for path in files:
        result = _git(workspace, ["add", "--", path], check=False)
        outputs.append(_format_result(["git", "add", "--", path], result))
        if result.returncode != 0:
            return "\n\n".join(outputs)

    commit = _git(workspace, ["commit", "-m", message], check=False)
    outputs.append(_format_result(["git", "commit", "-m", message], commit))
    if commit.returncode != 0:
        return "\n\n".join(outputs)

    push = _git(workspace, ["push"], check=False)
    outputs.append(_format_result(["git", "push"], push))
    return "\n\n".join(outputs)


def stage_paths(workspace: Path, paths: list[str]) -> str:
    safe_paths = _validate_git_paths(workspace, paths)
    outputs = []
    for path in safe_paths:
        result = _git(workspace, ["add", "--", path], check=False)
        outputs.append(_format_result(["git", "add", "--", path], result))
        if result.returncode != 0:
            break
    return "\n\n".join(outputs)


def unstage_paths(workspace: Path, paths: list[str]) -> str:
    safe_paths = _validate_git_paths(workspace, paths)
    outputs = []
    for path in safe_paths:
        result = _git(workspace, ["restore", "--staged", "--", path], check=False)
        outputs.append(_format_result(["git", "restore", "--staged", "--", path], result))
        if result.returncode != 0:
            break
    return "\n\n".join(outputs)


def push_current_branch(workspace: Path) -> str:
    upstream = _git(
        workspace,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
    )
    if upstream.returncode != 0:
        return (
            "$ git rev-parse --abbrev-ref --symbolic-full-name @{u}\n"
            f"exit={upstream.returncode}\n"
            "push aborted: current branch has no upstream. "
            "Configure upstream manually before using /push."
        )

    push = _git(workspace, ["push"], check=False)
    return _format_result(["git", "push"], push)


def _validate_git_paths(workspace: Path, paths: list[str]) -> list[str]:
    if not paths:
        raise GitPathError("at least one explicit file path is required")

    workspace = workspace.resolve()
    safe_paths: list[str] = []
    for raw in paths:
        path = str(raw).strip()
        if not path:
            raise GitPathError("empty path is not allowed")
        if path in {".", "./", "*"}:
            raise GitPathError(f"broad git path is not allowed: {path}")
        if path.startswith("-"):
            raise GitPathError(f"git option-like path is not allowed: {path}")
        if any(char in path for char in "*?["):
            raise GitPathError(f"glob path is not allowed: {path}")

        target = (workspace / path).resolve()
        if workspace != target and workspace not in target.parents:
            raise GitPathError(f"path escapes workspace: {path}")
        if target.is_dir():
            raise GitPathError(f"directory path is not allowed: {path}")

        safe_paths.append(target.relative_to(workspace).as_posix())

    return list(dict.fromkeys(safe_paths))


def _git(workspace: Path, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=120,
        check=check,
    )


def _format_result(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout + result.stderr).strip()
    return f"$ {' '.join(command)}\nexit={result.returncode}\n{output}"
