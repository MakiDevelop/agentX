from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol


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
    skipped = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules"}
    files = []
    for item in sorted(workspace.rglob("*")):
        relative = item.relative_to(workspace)
        if any(part in skipped for part in relative.parts):
            continue
        if item.is_file():
            files.append(str(relative))
        if len(files) >= limit:
            break
    return "--- file inventory ---\n" + "\n".join(files)
