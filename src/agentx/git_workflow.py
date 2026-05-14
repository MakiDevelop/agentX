from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitCommitPlan:
    status: str
    diff_stat: str
    files: list[str]


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
