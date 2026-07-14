from __future__ import annotations

from enum import Enum


class Risk(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


READ_ONLY_TOOLS = {
    "list_files",
    "read_file",
    "search_text",
    "infrastructure_context",
    "analyze_intent",
    "plan_task",
    "locate_topic",
    "git_status",
    "git_branch",
    "git_log",
    "git_show",
    "git_diff",
    "memory_search",
    "run_command",
    "web_fetch",
    "run_tests",
    "docker_compose_ps",
    "docker_compose_logs",
}

YELLOW_TOOLS = {
    "apply_patch",
    "search_replace",
    "insert_code",
    "docker_compose_build",
    "docker_compose_down",
    "docker_compose_up",
    "memory_write",
    "git_stage",
    "git_unstage",
    "git_push",
}

RED_COMMAND_PATTERNS = (
    "rm -rf",
    "rm -r",
    "--delete",
    "--remove-source-files",
    "chmod -R",
    "chown -R",
    "git push --force",
    "git push -f",
)

SENSITIVE_PATHS = (
    "~/.ssh",
    "~/.gnupg",
    ".secrets",
    "/.ssh",
    "/.gnupg",
    "/.secrets",
)


def classify_tool(tool: str) -> Risk:
    if tool in READ_ONLY_TOOLS:
        return Risk.GREEN
    if tool in YELLOW_TOOLS:
        return Risk.YELLOW
    return Risk.RED


def classify_command(command: str) -> Risk:
    normalized = " ".join(command.strip().split())
    lowered = normalized.lower()
    if any(pattern.lower() in lowered for pattern in RED_COMMAND_PATTERNS):
        return Risk.RED
    if any(path in normalized for path in SENSITIVE_PATHS):
        return Risk.RED
    if lowered.startswith("mv ") and _looks_like_absolute_multi_path_move(normalized):
        return Risk.RED
    return Risk.YELLOW


def _looks_like_absolute_multi_path_move(command: str) -> bool:
    """Conservative cross-device move guard.

    We cannot know the device boundary from a raw command string, so absolute
    multi-path mv commands are treated as RED and should be decomposed into a
    copy/verify/delete workflow by the human.
    """
    parts = command.split()
    if len(parts) < 3:
        return False
    paths = [part for part in parts[1:] if part.startswith("/") or part.startswith("~")]
    return len(paths) >= 2


def require_allowed(tool: str) -> None:
    risk = classify_tool(tool)
    if risk == Risk.RED:
        raise PermissionError(f"Tool is blocked by safety policy: {tool}")
