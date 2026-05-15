from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

from agentx.tools import SKIPPED_DIRS


BOOTSTRAP_FILES = ("AGENTS.md", "README.md", "pyproject.toml", "package.json")


class MemorySearcher(Protocol):
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str: ...


def build_repo_context(workspace: Path, max_chars: int = 12000) -> str:
    parts = [f"Workspace: {workspace}"]
    parts.append(_git_status(workspace))
    parts.append(_file_inventory(workspace))

    for filename in BOOTSTRAP_FILES:
        path = workspace / filename
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"--- {filename} ---\n{content[:3000]}")

    context = "\n\n".join(part for part in parts if part.strip())
    return context[:max_chars]


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
