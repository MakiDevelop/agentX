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
    "git_status",
    "git_diff",
    "memory_search",
    "run_command",
    "run_tests",
}

YELLOW_TOOLS = {
    "apply_patch",
    "memory_write",
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
)


def classify_tool(tool: str) -> Risk:
    if tool in READ_ONLY_TOOLS:
        return Risk.GREEN
    if tool in YELLOW_TOOLS:
        return Risk.YELLOW
    return Risk.RED


def classify_command(command: str) -> Risk:
    normalized = " ".join(command.strip().split())
    if any(pattern in normalized for pattern in RED_COMMAND_PATTERNS):
        return Risk.RED
    if any(path in normalized for path in SENSITIVE_PATHS):
        return Risk.RED
    return Risk.YELLOW


def require_allowed(tool: str) -> None:
    risk = classify_tool(tool)
    if risk == Risk.RED:
        raise PermissionError(f"Tool is blocked by safety policy: {tool}")
