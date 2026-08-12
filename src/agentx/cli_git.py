"""Git, diff and patch inspection payloads.

Extracted verbatim from cli.py, which had grown to 10,761 lines — 46% of the
entire source tree — with 326 top-level functions in one module.

This group was chosen as the first slice because it is *closed*: all twelve
functions depend only on each other and on imports, so moving them cannot create
a circular import back into cli.py. Larger families (workflow, reliability) call
across into command_plan/inspect/artifacts and need those seams broken first.

cli.py re-exports every name below, so `from agentx.cli import git_status_payload`
keeps working for existing callers and tests.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from agentx.config import Settings
from agentx.proc import run_process
from agentx.tools._helpers import (
    ensure_safe_write_path,
    patch_write_paths,
    resolve_inside_workspace,
)

__all__ = [
    "diff_payload",
    "git_status_payload",
    "patch_check_payload",
]


def _parse_git_branch_status(branch_line: str) -> dict[str, object]:
    if not branch_line.startswith("## "):
        return {
            "branch": None,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "initial": False,
        }

    head = branch_line.removeprefix("## ").strip()
    meta = ""
    if " [" in head and head.endswith("]"):
        head, meta = head.rsplit(" [", 1)
        meta = meta.rstrip("]")

    initial_prefix = "No commits yet on "
    initial = head.startswith(initial_prefix)
    detached = head.startswith("HEAD ") or head == "HEAD"
    branch = head.removeprefix(initial_prefix) if initial else head
    upstream = None
    if "..." in branch:
        branch, upstream = branch.split("...", 1)

    ahead = 0
    behind = 0
    if meta:
        for item in [part.strip() for part in meta.split(",")]:
            if item.startswith("ahead "):
                ahead = int(item.removeprefix("ahead ").strip() or "0")
            elif item.startswith("behind "):
                behind = int(item.removeprefix("behind ").strip() or "0")

    return {
        "branch": branch or None,
        "upstream": upstream or None,
        "ahead": ahead,
        "behind": behind,
        "detached": detached,
        "initial": initial,
    }


def git_status_payload(workspace: Path) -> dict[str, object]:
    try:
        # --porcelain=v1 (not --short): the branch header and status codes are a
        # documented machine contract and are never translated. See agentx.proc.
        result = run_process(
            ["git", "status", "--porcelain=v1", "--branch"],
            cwd=workspace,
            timeout=10,
        )
    except Exception as exc:
        return {
            "ok": False,
            "branch": None,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "initial": False,
            "dirty": None,
            "changes_count": None,
            "changes": [],
            "detail": f"{type(exc).__name__}: {exc}",
        }

    output = (result.stdout or result.stderr or "").strip()
    lines = output.splitlines()
    branch_line = lines[0] if lines and lines[0].startswith("## ") else ""
    changes = lines[1:] if branch_line else lines
    parsed = _parse_git_branch_status(branch_line)
    return {
        "ok": result.returncode == 0,
        **parsed,
        "dirty": bool(changes) if result.returncode == 0 else None,
        "changes_count": len(changes) if result.returncode == 0 else None,
        "changes": changes[:50],
        "detail": "" if result.returncode == 0 else output,
    }


def _git_read(
    workspace: Path,
    args: list[str],
    *,
    timeout: int = 10,
) -> tuple[int, str, str]:
    result = run_process(
        ["git", *args],
        cwd=workspace,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _diff_relative_path(workspace: Path, path: str | None) -> str | None:
    if path in (None, ""):
        return None
    target = resolve_inside_workspace(workspace, path)
    return str(target.relative_to(workspace))


def _parse_diff_numstat(output: str) -> dict[str, dict[str, object]]:
    parsed: dict[str, dict[str, object]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, file_path = parts[0], parts[1], parts[2]
        binary = added_raw == "-" or deleted_raw == "-"
        added = None if binary else int(added_raw)
        deleted = None if binary else int(deleted_raw)
        parsed[file_path] = {
            "path": file_path,
            "added": added,
            "deleted": deleted,
            "binary": binary,
        }
    return parsed


def _parse_diff_name_status(output: str) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3 or status.startswith("C") and len(parts) >= 3:
            files.append({"status": status, "path": parts[2], "old_path": parts[1]})
        else:
            files.append({"status": status, "path": parts[1]})
    return files


def _parse_untracked_status(output: str) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.startswith("?? "):
            continue
        file_path = line[3:].strip()
        if file_path:
            files.append(
                {
                    "status": "??",
                    "path": file_path,
                    "added": None,
                    "deleted": None,
                    "binary": False,
                }
            )
    return files


def _diff_args(*, staged: bool, path: str | None) -> list[str]:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    return args


def diff_payload(
    settings: Settings,
    *,
    path: str | None = None,
    staged: bool = False,
    include_patch: bool = False,
    max_patch_chars: int = 20000,
) -> dict[str, object]:
    workspace = settings.workspace
    relative_path = _diff_relative_path(workspace, path)
    try:
        repo_code, repo_stdout, repo_stderr = _git_read(
            workspace, ["rev-parse", "--is-inside-work-tree"]
        )
    except Exception as exc:
        return {
            "schema": "agentx.diff.v1",
            "workspace": str(workspace),
            "path": relative_path,
            "staged": staged,
            "ok": False,
            "is_git_repo": False,
            "dirty": None,
            "file_count": 0,
            "insertions": 0,
            "deletions": 0,
            "binary_count": 0,
            "untracked_count": 0,
            "files": [],
            "stat": "",
            "patch_included": include_patch,
            "patch": None,
            "patch_truncated": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    is_git_repo = repo_code == 0 and repo_stdout.strip() == "true"
    if not is_git_repo:
        detail = (repo_stderr or repo_stdout).strip()
        return {
            "schema": "agentx.diff.v1",
            "workspace": str(workspace),
            "path": relative_path,
            "staged": staged,
            "ok": False,
            "is_git_repo": False,
            "dirty": None,
            "file_count": 0,
            "insertions": 0,
            "deletions": 0,
            "binary_count": 0,
            "untracked_count": 0,
            "files": [],
            "stat": "",
            "patch_included": include_patch,
            "patch": None,
            "patch_truncated": False,
            "detail": detail or "not a git repository",
        }

    base_args = _diff_args(staged=staged, path=relative_path)
    stat_code, stat_stdout, stat_stderr = _git_read(workspace, [*base_args, "--stat"])
    numstat_code, numstat_stdout, numstat_stderr = _git_read(workspace, [*base_args, "--numstat"])
    status_code, status_stdout, status_stderr = _git_read(workspace, [*base_args, "--name-status"])
    untracked_code = 0
    untracked_stdout = ""
    untracked_stderr = ""
    if not staged:
        status_args = ["status", "--porcelain", "--untracked-files=all"]
        if relative_path:
            status_args.extend(["--", relative_path])
        untracked_code, untracked_stdout, untracked_stderr = _git_read(workspace, status_args)
    ok = stat_code == 0 and numstat_code == 0 and status_code == 0
    ok = ok and (staged or untracked_code == 0)

    numstat = _parse_diff_numstat(numstat_stdout if numstat_code == 0 else "")
    files = []
    for item in _parse_diff_name_status(status_stdout if status_code == 0 else ""):
        file_path = str(item["path"])
        stats = numstat.get(file_path, {})
        files.append(
            {
                **item,
                "added": stats.get("added"),
                "deleted": stats.get("deleted"),
                "binary": bool(stats.get("binary", False)),
            }
        )
    existing_paths = {str(item.get("path")) for item in files}
    untracked_files = [
        item
        for item in _parse_untracked_status(untracked_stdout if untracked_code == 0 else "")
        if str(item.get("path")) not in existing_paths
    ]
    files.extend(untracked_files)

    insertions = sum(int(item["added"]) for item in files if isinstance(item.get("added"), int))
    deletions = sum(int(item["deleted"]) for item in files if isinstance(item.get("deleted"), int))
    binary_count = sum(1 for item in files if item.get("binary") is True)
    untracked_count = len(untracked_files)
    patch_text = None
    patch_truncated = False
    patch_detail = ""
    if include_patch:
        patch_code, patch_stdout, patch_stderr = _git_read(workspace, base_args, timeout=20)
        ok = ok and patch_code == 0
        patch_text = patch_stdout[:max_patch_chars]
        patch_truncated = len(patch_stdout) > max_patch_chars
        patch_detail = patch_stderr.strip() if patch_code != 0 else ""

    details = [
        detail.strip()
        for detail in (stat_stderr, numstat_stderr, status_stderr, patch_detail)
        if detail.strip()
    ]
    if untracked_stderr.strip():
        details.append(untracked_stderr.strip())
    return {
        "schema": "agentx.diff.v1",
        "workspace": str(workspace),
        "path": relative_path,
        "staged": staged,
        "ok": ok,
        "is_git_repo": True,
        "dirty": bool(files),
        "file_count": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "binary_count": binary_count,
        "untracked_count": untracked_count,
        "files": files,
        "stat": stat_stdout if stat_code == 0 else "",
        "patch_included": include_patch,
        "patch": patch_text,
        "patch_truncated": patch_truncated,
        "detail": "\n".join(details),
    }


def _git_apply_read(
    workspace: Path,
    args: list[str],
    *,
    patch: str,
    timeout: int = 20,
) -> tuple[int, str, str]:
    completed = run_process(
        ["git", "apply", *args, "-"],
        cwd=workspace,
        input=patch,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _patch_check_relative_path(workspace: Path, patch_file: str) -> tuple[Path | None, str, str]:
    try:
        target = resolve_inside_workspace(workspace, patch_file)
    except ValueError as exc:
        return None, patch_file, str(exc)
    try:
        relative = str(target.relative_to(workspace))
    except ValueError:
        relative = patch_file
    return target, relative, ""


def patch_check_payload(
    settings: Settings,
    *,
    patch_file: str,
    timeout: int = 20,
) -> dict[str, object]:
    workspace = settings.workspace
    patch_path, relative_patch, path_error = _patch_check_relative_path(workspace, patch_file)
    blockers: list[str] = []
    warnings: list[str] = []
    details: list[str] = []
    patch_text = ""

    if path_error:
        blockers.append("patch_file_escapes_workspace")
        details.append(path_error)
    elif patch_path is None or not patch_path.is_file():
        blockers.append("patch_file_not_found")
        details.append(f"patch file not found: {patch_file}")
    else:
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
        if not patch_text.strip():
            blockers.append("empty_patch")

    parsed_paths = patch_write_paths(patch_text) if patch_text else set()
    name_only_paths: set[str] = set()
    numstat: dict[str, dict[str, object]] = {}
    apply_check = {
        "command": "git apply --check -",
        "ok": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    if patch_text:
        try:
            check_code, check_stdout, check_stderr = _git_apply_read(
                workspace,
                ["--check"],
                patch=patch_text,
                timeout=timeout,
            )
            apply_check = {
                "command": "git apply --check -",
                "ok": check_code == 0,
                "exit_code": check_code,
                "stdout": check_stdout,
                "stderr": check_stderr,
            }
            if check_code != 0:
                blockers.append("git_apply_check_failed")
                details.append((check_stderr or check_stdout).strip())
        except subprocess.TimeoutExpired:
            blockers.append("git_apply_check_timeout")
            apply_check = {
                "command": "git apply --check -",
                "ok": False,
                "exit_code": 124,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
            }
            details.append(f"git apply --check timed out after {timeout}s")

        for args, collector in ((["--name-only"], name_only_paths),):
            try:
                code, stdout, _stderr = _git_apply_read(
                    workspace, args, patch=patch_text, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                warnings.append("git_apply_name_only_timeout")
                continue
            if code == 0:
                for line in stdout.splitlines():
                    path = line.strip()
                    if path and path != "/dev/null":
                        collector.add(path)

        try:
            numstat_code, numstat_stdout, _numstat_stderr = _git_apply_read(
                workspace,
                ["--numstat"],
                patch=patch_text,
                timeout=timeout,
            )
            if numstat_code == 0:
                numstat = _parse_diff_numstat(numstat_stdout)
        except subprocess.TimeoutExpired:
            warnings.append("git_apply_numstat_timeout")

    touched_paths = sorted(
        path for path in {*parsed_paths, *name_only_paths} if path and path != "/dev/null"
    )
    files: list[dict[str, object]] = []
    unsafe_paths: list[str] = []
    for path in touched_paths:
        stats = numstat.get(path, {})
        safe = True
        safe_detail = ""
        try:
            ensure_safe_write_path(workspace, resolve_inside_workspace(workspace, path))
        except ValueError as exc:
            safe = False
            safe_detail = str(exc)
            unsafe_paths.append(path)
        files.append(
            {
                "path": path,
                "added": stats.get("added"),
                "deleted": stats.get("deleted"),
                "binary": bool(stats.get("binary", False)),
                "safe": safe,
                "detail": safe_detail,
                "source": sorted(
                    source
                    for source, paths in (("parsed", parsed_paths), ("git", name_only_paths))
                    if path in paths
                ),
            }
        )
    if unsafe_paths:
        blockers.append("unsafe_patch_paths")
        details.extend(f"{path}: unsafe patch target" for path in unsafe_paths)
    if patch_text and not touched_paths:
        warnings.append("no_touched_paths_detected")

    ok = not blockers
    next_commands = ["agentx diff --json"]
    if ok:
        next_commands.append(f"/apply {relative_patch}")
        recommended_command = f"/apply {relative_patch}"
        recommended_kind = "apply_patch"
        recommended_risk = "YELLOW"
    else:
        next_commands.append("fix patch blockers, then rerun agentx patch-check PATCH --json")
        recommended_command = "fix patch blockers, then rerun agentx patch-check PATCH --json"
        recommended_kind = "fix_patch_blockers"
        recommended_risk = "UNKNOWN"

    return {
        "schema": "agentx.patch_check.v1",
        "workspace": str(workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "patch_file": relative_patch,
        "ok": ok,
        "blockers": blockers,
        "warnings": warnings,
        "apply_check": apply_check,
        "safe_paths_ok": not unsafe_paths,
        "file_count": len(files),
        "files": files,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "next_commands": next_commands,
        "detail": "\n".join(detail for detail in details if detail),
    }
