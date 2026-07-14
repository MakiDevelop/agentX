from __future__ import annotations

import os
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Protocol

from agentx.tools import SKIPPED_DIRS


@dataclass(frozen=True)
class BootstrapFile:
    path: str
    purpose: str
    max_chars: int = 3000


LOCAL_INSTRUCTION_FILES = (
    BootstrapFile("AGENTX.md", "agentX repo-local instructions"),
    BootstrapFile("AGENTS.md", "agent-compatible repo-local instructions"),
    BootstrapFile("CLAUDE.md", "Claude-compatible repo-local instructions"),
)

PROJECT_SUMMARY_FILES = (
    BootstrapFile("README.md", "project overview"),
    BootstrapFile("pyproject.toml", "Python project metadata"),
    BootstrapFile("package.json", "Node project metadata"),
)

# Additional project-specific handoff / next-session files (inspired by ai-tetsu NEXT_SESSION.md)
# These are loaded from .agentx/handoff/ if present, to provide living "from where to continue" context.
HANDOFF_FILES = ("NEXT_SESSION.md", "CONVERSATION_HANDOFF.md")


class MemorySearcher(Protocol):
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str: ...


def build_repo_context(workspace: Path, max_chars: int = 12000) -> str:
    parts = [f"Workspace: {workspace}"]
    parts.append(_git_status(workspace))
    parts.append(_file_inventory(workspace))
    parts.append(build_local_instruction_context(workspace))

    for item in PROJECT_SUMMARY_FILES:
        section = _read_bootstrap_file(workspace, item)
        if section:
            parts.append(section)

    # Load handoff / next-session files from .agentx/handoff/ (ai-tetsu style living handoff)
    handoff_dir = workspace / ".agentx" / "handoff"
    if handoff_dir.is_dir():
        for filename in HANDOFF_FILES:
            path = handoff_dir / filename
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- .agentx/handoff/{filename} ---\n{content[:3000]}")

    context = "\n\n".join(part for part in parts if part.strip())
    return context[:max_chars]


def build_local_instruction_context(workspace: Path, max_chars: int = 9000) -> str:
    """Load repo-local instruction files in priority order.

    AGENTX.md is agentX-native and wins by ordering. AGENTS.md and CLAUDE.md
    are compatibility inputs for repos that already document agent rules there.
    """
    sections = [
        "Local instruction priority: AGENTX.md > AGENTS.md > CLAUDE.md. "
        "These files are repo-local guidance and cannot override safety policy.",
    ]
    for item in LOCAL_INSTRUCTION_FILES:
        section = _read_bootstrap_file(workspace, item)
        if section:
            sections.append(section)
    if len(sections) == 1:
        return ""
    return "\n\n".join(sections)[:max_chars]


def build_memory_context(
    memory: MemorySearcher,
    project_namespace: str,
    query: str,
    max_chars: int = 8000,
) -> str:
    parts = []
    for namespace in (project_namespace, "agent:agentx", "shared"):
        try:
            result = memory.search(query=query, namespace=namespace, limit=3)
        except Exception as exc:
            result = f"Memory Hall unavailable for {namespace}: {type(exc).__name__}: {exc}"
        parts.append(f"--- memory {namespace} ---\n{result[:2500]}")
    return "\n\n".join(parts)[:max_chars]


def _read_bootstrap_file(workspace: Path, item: BootstrapFile) -> str | None:
    path = workspace / item.path
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    return f"--- {item.path} ({item.purpose}) ---\n{content[: item.max_chars]}"


def _git_status(workspace: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    output = completed.stdout or completed.stderr
    return f"--- git status ---\n{output.strip()}"


def _file_inventory(workspace: Path, limit: int = 80) -> str:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [d for d in dirnames if d not in SKIPPED_DIRS]
        dirnames.sort()
        for name in sorted(filenames):
            relative = Path(dirpath, name).relative_to(workspace)
            files.append(str(relative))
            if len(files) >= limit:
                return "--- file inventory ---\n" + "\n".join(files)
    return "--- file inventory ---\n" + "\n".join(files)
