from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentx.memory_hall import MemoryHallClient
from agentx.protocol import Tool
from agentx.safety import Risk
from agentx.tools._helpers import (
    ALLOWED_COMMANDS,
    SKIPPED_DIRS,
    docker_compose_command,
    resolve_inside_workspace,
    run_subprocess,
)


class _WorkspaceTool:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()


class ListFilesTool(_WorkspaceTool):
    name = "list_files"
    description = "列出 workspace 內檔案，會跳過 .git/.venv/cache 目錄"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        path = args.get("path", ".")
        limit = int(args.get("limit", 200))
        root = resolve_inside_workspace(self.workspace, path)
        if not root.exists():
            raise FileNotFoundError(path)
        files: list[str] = []
        for item in sorted(root.rglob("*")):
            if any(part in SKIPPED_DIRS for part in item.relative_to(self.workspace).parts):
                continue
            if item.is_file():
                files.append(str(item.relative_to(self.workspace)))
            if len(files) >= limit:
                break
        return "\n".join(files)


class ReadFileTool(_WorkspaceTool):
    name = "read_file"
    description = "讀取 workspace 內指定檔案內容"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        path = args["path"]
        max_chars = int(args.get("max_chars", 20000))
        target = resolve_inside_workspace(self.workspace, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text(encoding="utf-8", errors="replace")[:max_chars]


class SearchTextTool(_WorkspaceTool):
    name = "search_text"
    description = "使用 rg 搜尋 workspace 內文字"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        pattern = args["pattern"]
        path = args.get("path", ".")
        limit = int(args.get("limit", 100))
        root = resolve_inside_workspace(self.workspace, path)
        _, output = run_subprocess(
            ["rg", "--line-number", "--color", "never", pattern, str(root)],
            cwd=self.workspace,
        )
        return "\n".join(output.splitlines()[:limit])


class GitStatusTool(_WorkspaceTool):
    name = "git_status"
    description = "查看 git status --short --branch"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        _, output = run_subprocess(["git", "status", "--short", "--branch"], cwd=self.workspace)
        return output


class GitDiffTool(_WorkspaceTool):
    name = "git_diff"
    description = "查看 git diff，可指定單一 path"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        max_chars = int(args.get("max_chars", 30000))
        cmd = ["git", "diff"]
        if path:
            resolve_inside_workspace(self.workspace, path)
            cmd.extend(["--", path])
        _, output = run_subprocess(cmd, cwd=self.workspace)
        return output[:max_chars]


class MemorySearchTool:
    name = "memory_search"
    description = "查詢 Memory Hall"
    risk = Risk.GREEN

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        return self.memory.search(
            query=args["query"],
            namespace=args.get("namespace", "shared"),
            limit=int(args.get("limit", 5)),
        )


class MemoryWriteTool:
    name = "memory_write"
    description = "寫入 Memory Hall"
    risk = Risk.YELLOW

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        return self.memory.write(
            content=args["content"],
            namespace=args.get("namespace", "agent:agentx"),
        )


class RunCommandTool(_WorkspaceTool):
    name = "run_command"
    description = "執行固定 allowlist 命令"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        command = args["command"]
        if command not in ALLOWED_COMMANDS:
            allowed = "\n".join(f"- {item}" for item in sorted(ALLOWED_COMMANDS))
            raise PermissionError(f"Command is not allowlisted: {command}\nAllowed:\n{allowed}")
        completed = subprocess.run(
            ALLOWED_COMMANDS[command],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        output = completed.stdout or completed.stderr
        return f"$ {command}\nexit={completed.returncode}\n{output.strip()}"


class RunTestsTool(_WorkspaceTool):
    name = "run_tests"
    description = "執行固定 allowlist 驗證：ruff check 與 pytest"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        commands = [
            ["uv", "run", "ruff", "check", "."],
            ["uv", "run", "pytest", "-q"],
        ]
        outputs: list[str] = []
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


class ApplyPatchTool(_WorkspaceTool):
    name = "apply_patch"
    description = "套用 unified diff patch，需 approval"
    risk = Risk.YELLOW

    def run(self, args: dict[str, Any]) -> str:
        patch = args["patch"]
        patch_dir = self.workspace / ".agentx" / "patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / "pending.patch"
        patch_path.write_text(patch, encoding="utf-8")

        check = subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if check.returncode != 0:
            return f"git apply --check failed\n{check.stdout}{check.stderr}".strip()

        applied = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        output = (applied.stdout + applied.stderr).strip()
        if applied.returncode != 0:
            return f"git apply failed\n{output}".strip()
        return output or "patch applied"


class _DockerComposeTool(_WorkspaceTool):
    action: str = ""

    def _run_action(self, args: dict[str, Any]) -> str:
        command = docker_compose_command(
            self.workspace,
            self.action,
            compose_file=args.get("compose_file"),
            service=args.get("service"),
            tail=int(args.get("tail", 100)),
        )
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        output = completed.stdout or completed.stderr
        return f"$ {' '.join(command)}\nexit={completed.returncode}\n{output.strip()}"


class DockerComposePsTool(_DockerComposeTool):
    name = "docker_compose_ps"
    description = "查看 docker compose ps"
    risk = Risk.GREEN
    action = "ps"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeBuildTool(_DockerComposeTool):
    name = "docker_compose_build"
    description = "執行 docker compose build，需 approval"
    risk = Risk.YELLOW
    action = "build"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeUpTool(_DockerComposeTool):
    name = "docker_compose_up"
    description = "執行 docker compose up -d，需 approval"
    risk = Risk.YELLOW
    action = "up"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeDownTool(_DockerComposeTool):
    name = "docker_compose_down"
    description = "執行 docker compose down，需 approval"
    risk = Risk.YELLOW
    action = "down"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeLogsTool(_DockerComposeTool):
    name = "docker_compose_logs"
    description = "查看 docker compose logs"
    risk = Risk.GREEN
    action = "logs"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


def builtin_tools(workspace: Path, memory: MemoryHallClient) -> list[Tool]:
    return [
        ListFilesTool(workspace),
        ReadFileTool(workspace),
        SearchTextTool(workspace),
        GitStatusTool(workspace),
        GitDiffTool(workspace),
        MemorySearchTool(memory),
        MemoryWriteTool(memory),
        RunCommandTool(workspace),
        RunTestsTool(workspace),
        ApplyPatchTool(workspace),
        DockerComposePsTool(workspace),
        DockerComposeBuildTool(workspace),
        DockerComposeUpTool(workspace),
        DockerComposeDownTool(workspace),
        DockerComposeLogsTool(workspace),
    ]
