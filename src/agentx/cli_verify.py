"""Verify, review and commit-plan payloads.

The "am I ready to commit?" surface: run the project's checks, summarise what
changed, and propose a commit plan. Extracted from cli.py as the second slice of
`docs/CLI_SPLIT_PLAN.md`.

This group only became extractable after `cli_output.py` was pulled out — until
then it referenced `console` and `print_structured_payload` from cli.py, so
moving it would have created a circular import. That is the general shape of the
remaining work: break the shared seam first, then whole families come free.

Verified closed with `scripts/find_closed_groups.py`: the transitive closure of
these ten functions refers to nothing else defined at cli.py's top level.
"""

from __future__ import annotations

import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from rich.table import Table

from agentx.cli_git import diff_payload
from agentx.cli_output import console, print_structured_payload
from agentx.config import Settings
from agentx.git_workflow import build_commit_plan
from agentx.proc import run_process

__all__ = [
    "commit_plan_exit_code",
    "commit_plan_payload",
    "default_verify_commands",
    "print_commit_plan_payload",
    "print_review_payload",
    "review_exit_code",
    "review_payload",
    "verify_exit_code",
    "verify_payload",
    "verify_payload_from_checks",
]


def default_verify_commands(workspace: Path) -> list[list[str]]:
    files = {path.name for path in workspace.iterdir()}
    commands: list[list[str]] = []
    if "pyproject.toml" in files:
        commands.extend(
            [
                ["uv", "run", "ruff", "check", "."],
                ["uv", "run", "pytest", "-q"],
            ]
        )
    if "package.json" in files:
        commands.append(["npm", "test"])
    return commands


def verify_payload_from_checks(
    checks: list[dict[str, object]],
    *,
    settings: Settings,
) -> dict[str, object]:
    ok = bool(checks) and all(bool(check.get("ok")) for check in checks)
    if ok:
        recommended_command = "agentx review --json"
        recommended_kind = "review"
        recommended_risk = "GREEN"
    else:
        recommended_command = (
            "fix verification failures, then rerun agentx verify --json --fail-on-error"
        )
        recommended_kind = "fix_verify"
        recommended_risk = "UNKNOWN"
    return {
        "schema": "agentx.verify.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "count": len(checks),
        "checks": checks,
    }


def verify_payload(
    settings: Settings,
    *,
    timeout: int = 120,
    output_limit: int = 12000,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    commands = default_verify_commands(settings.workspace)
    if not commands:
        return verify_payload_from_checks(
            [
                {
                    "command": "",
                    "argv": [],
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "output": "no default verification commands detected",
                }
            ],
            settings=settings,
        )

    for command in commands:
        command_text = shlex.join(command)
        try:
            completed = run_process(
                command,
                cwd=settings.workspace,
                timeout=timeout,
            )
            stdout = (completed.stdout or "")[:output_limit]
            stderr = (completed.stderr or "")[:output_limit]
            output = (completed.stdout or completed.stderr or "")[:output_limit]
            check = {
                "command": command_text,
                "argv": command,
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            check = {
                "command": command_text,
                "argv": command,
                "ok": False,
                "exit_code": 124,
                "stdout": stdout[:output_limit],
                "stderr": stderr[:output_limit],
                "output": f"timeout after {timeout}s",
            }
        checks.append(check)
        if not check["ok"]:
            break

    return verify_payload_from_checks(checks, settings=settings)


def verify_exit_code(payload: dict[str, object], *, fail_on_error: bool = False) -> int:
    if not fail_on_error:
        return 0
    return 0 if payload.get("ok") is True else 1


def review_payload(
    settings: Settings,
    *,
    timeout: int = 120,
    run_verify: bool = True,
) -> dict[str, object]:
    diff = diff_payload(settings)
    verify = verify_payload(settings, timeout=timeout) if run_verify else None
    blockers: list[str] = []
    warnings: list[str] = []

    if diff.get("ok") is not True:
        blockers.append("diff_unavailable")
    elif diff.get("dirty") is not True:
        blockers.append("no_changes")

    if verify is None:
        warnings.append("verify_skipped")
    elif verify.get("ok") is not True:
        blockers.append("verify_failed")

    if diff.get("untracked_count", 0):
        warnings.append("has_untracked_files")

    commit_ready = not blockers and verify is not None
    next_commands = ["agentx diff --json"]
    if verify is None:
        next_commands.append("agentx verify --json --fail-on-error")
    if commit_ready:
        next_commands.append("/commit 中文訊息")
        recommended_command = "/commit 中文訊息"
        recommended_kind = "commit"
        recommended_risk = "YELLOW"
    elif blockers:
        next_commands.append("fix blockers, then rerun agentx review --json")
        recommended_command = "fix blockers, then rerun agentx review --json"
        recommended_kind = "fix_blockers"
        recommended_risk = "UNKNOWN"
    elif verify is None:
        recommended_command = "agentx verify --json --fail-on-error"
        recommended_kind = "verify"
        recommended_risk = "GREEN"
    else:
        next_commands.append("agentx review --json")
        recommended_command = "agentx review --json"
        recommended_kind = "review"
        recommended_risk = "GREEN"

    return {
        "schema": "agentx.review.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not blockers,
        "commit_ready": commit_ready,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "blockers": blockers,
        "warnings": warnings,
        "diff": diff,
        "verify": verify,
        "next_commands": next_commands,
    }


def print_review_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="review",
        )
        return

    diff = dict(payload["diff"])  # type: ignore[arg-type]
    verify = payload.get("verify")
    verify_ok = None if verify is None else dict(verify).get("ok")  # type: ignore[arg-type]
    table = Table(title="agentX review gate", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload["ok"]))
    table.add_row("commit_ready", str(payload["commit_ready"]))
    table.add_row(
        "diff",
        f"dirty={diff.get('dirty')} files={diff.get('file_count')} "
        f"insertions={diff.get('insertions')} deletions={diff.get('deletions')} "
        f"untracked={diff.get('untracked_count')}",
    )
    table.add_row("verify", "skipped" if verify is None else f"ok={verify_ok}")
    table.add_row("blockers", ", ".join(str(item) for item in payload["blockers"]) or "-")
    table.add_row("warnings", ", ".join(str(item) for item in payload["warnings"]) or "-")
    console.print(table)


def review_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1


def commit_plan_payload(
    settings: Settings,
    *,
    message: str | None = None,
    timeout: int = 120,
    run_verify: bool = True,
) -> dict[str, object]:
    plan = build_commit_plan(settings.workspace)
    review = review_payload(settings, timeout=timeout, run_verify=run_verify)
    commit_message = (message or "").strip()
    blockers = [str(item) for item in review.get("blockers", [])]
    warnings = [str(item) for item in review.get("warnings", [])]
    if not commit_message:
        blockers.append("missing_commit_message")
    review_commit_ready = review.get("commit_ready") is True
    ready_to_commit = not blockers and review_commit_ready and bool(plan.files)
    next_commands = ["agentx diff --json"]
    if not commit_message:
        next_commands.append("agentx commit-plan --message '中文 commit 訊息' --json")
    if ready_to_commit:
        next_commands.append(f"/commit {commit_message}")
        recommended_command = f"/commit {commit_message}"
        recommended_kind = "commit"
        recommended_risk = "YELLOW"
    elif blockers:
        next_commands.append(
            "fix blockers, then rerun agentx commit-plan --message '中文 commit 訊息' --json"
        )
        recommended_command = (
            "fix blockers, then rerun agentx commit-plan --message '中文 commit 訊息' --json"
        )
        recommended_kind = "fix_blockers"
        recommended_risk = "UNKNOWN"
    elif not review_commit_ready:
        next_commands.append("agentx review --json --fail-on-blocker")
        recommended_command = "agentx review --json --fail-on-blocker"
        recommended_kind = "review"
        recommended_risk = "GREEN"
    else:
        recommended_command = "agentx commit-plan --message '中文 commit 訊息' --json"
        recommended_kind = "commit_plan"
        recommended_risk = "GREEN"

    return {
        "schema": "agentx.commit_plan.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not blockers,
        "ready_to_commit": ready_to_commit,
        "commit_message": commit_message or None,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "blockers": blockers,
        "warnings": warnings,
        "status": plan.status,
        "diff_stat": plan.diff_stat,
        "files_to_stage": plan.files,
        "file_count": len(plan.files),
        "review": review,
        "next_commands": next_commands,
    }


def print_commit_plan_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="commit_plan",
        )
        return

    table = Table(title="agentX commit plan", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload["ok"]))
    table.add_row("ready_to_commit", str(payload["ready_to_commit"]))
    table.add_row("commit_message", str(payload.get("commit_message") or "-"))
    table.add_row("files", str(payload["file_count"]))
    table.add_row("blockers", ", ".join(str(item) for item in payload["blockers"]) or "-")
    table.add_row("warnings", ", ".join(str(item) for item in payload["warnings"]) or "-")
    console.print(table)
    for path in payload["files_to_stage"]:  # type: ignore[index]
        console.print(f"- {path}")


def commit_plan_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1
