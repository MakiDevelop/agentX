from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentx.memory_hall import MemoryHallClient
from agentx.protocol import ToolResult
from agentx.safety import require_allowed


TOOL_DESCRIPTIONS = {
    "list_files": "列出 workspace 內檔案，會跳過 .git/.venv/cache 目錄",
    "read_file": "讀取 workspace 內指定檔案內容",
    "search_text": "使用 rg 搜尋 workspace 內文字",
    "git_status": "查看 git status --short --branch",
    "git_diff": "查看 git diff，可指定單一 path",
    "memory_search": "查詢 Memory Hall",
    "memory_write": "寫入 Memory Hall",
    "run_tests": "執行固定 allowlist 驗證：ruff check 與 pytest",
}

SKIPPED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


class ToolRegistry:
    def __init__(self, workspace: Path, memory: MemoryHallClient) -> None:
        self.workspace = workspace.resolve()
        self.memory = memory

    def describe_tools(self) -> dict[str, str]:
        return dict(TOOL_DESCRIPTIONS)

    def run(self, tool: str, args: dict[str, Any]) -> ToolResult:
        require_allowed(tool)
        try:
            method = getattr(self, f"_tool_{tool}")
        except AttributeError:
            return ToolResult(tool=tool, ok=False, content=f"Unknown tool: {tool}")

        try:
            content = method(**args)
            return ToolResult(tool=tool, ok=True, content=str(content))
        except Exception as exc:
            return ToolResult(tool=tool, ok=False, content=f"{type(exc).__name__}: {exc}")

    def _resolve_inside_workspace(self, path: str | None = None) -> Path:
        target = self.workspace if path in (None, "") else (self.workspace / path).resolve()
        if self.workspace != target and self.workspace not in target.parents:
            raise ValueError(f"Path escapes workspace: {path}")
        return target

    def _tool_list_files(self, path: str = ".", limit: int = 200) -> str:
        root = self._resolve_inside_workspace(path)
        if not root.exists():
            raise FileNotFoundError(path)
        files = []
        for item in sorted(root.rglob("*")):
            if any(part in SKIPPED_DIRS for part in item.relative_to(self.workspace).parts):
                continue
            if item.is_file():
                files.append(str(item.relative_to(self.workspace)))
            if len(files) >= limit:
                break
        return "\n".join(files)

    def _tool_read_file(self, path: str, max_chars: int = 20000) -> str:
        target = self._resolve_inside_workspace(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def _tool_search_text(self, pattern: str, path: str = ".", limit: int = 100) -> str:
        root = self._resolve_inside_workspace(path)
        cmd = ["rg", "--line-number", "--color", "never", pattern, str(root)]
        completed = subprocess.run(
            cmd,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        output = completed.stdout or completed.stderr
        lines = output.splitlines()[:limit]
        return "\n".join(lines)

    def _tool_git_status(self) -> str:
        return self._run_git(["status", "--short", "--branch"])

    def _tool_git_diff(self, path: str | None = None, max_chars: int = 30000) -> str:
        args = ["diff"]
        if path:
            self._resolve_inside_workspace(path)
            args.extend(["--", path])
        return self._run_git(args)[:max_chars]

    def _tool_memory_search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return self.memory.search(query=query, namespace=namespace, limit=limit)

    def _tool_memory_write(self, content: str, namespace: str = "agent:agentx") -> str:
        return self.memory.write(content=content, namespace=namespace)

    def _tool_run_tests(self) -> str:
        commands = [
            ["uv", "run", "ruff", "check", "."],
            ["uv", "run", "pytest", "-q"],
        ]
        outputs = []
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            output = completed.stdout or completed.stderr
            outputs.append(
                f"$ {' '.join(command)}\nexit={completed.returncode}\n{output.strip()}"
            )
            if completed.returncode != 0:
                break
        return "\n\n".join(outputs)

    def _run_git(self, args: list[str]) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return completed.stdout or completed.stderr
