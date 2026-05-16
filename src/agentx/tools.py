from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from agentx.memory_hall import MemoryHallClient
from agentx.protocol import ToolResult
from agentx.safety import Risk, classify_tool, require_allowed


TOOL_DESCRIPTIONS = {
    "list_files": "列出 workspace 內檔案，會跳過 .git/.venv/cache 目錄",
    "read_file": "讀取 workspace 內指定檔案內容",
    "search_text": "使用 rg 搜尋 workspace 內文字",
    "git_status": "查看 git status --short --branch",
    "git_diff": "查看 git diff，可指定單一 path",
    "memory_search": "查詢 Memory Hall",
    "memory_write": "寫入 Memory Hall",
    "run_command": "執行固定 allowlist 命令",
    "web_fetch": "讀取指定外部 http/https 網頁文字，會阻擋 localhost 與私有網段",
    "run_tests": "執行固定 allowlist 驗證：ruff check 與 pytest",
    "apply_patch": "套用 unified diff patch，需 approval",
    "search_replace": "精準搜尋替換（支援單檔多處或單處），比 apply_patch 更安全精確，需 approval",
    "insert_code": "在指定位置插入程式碼（after 某段文字後），適合新增函式、import 等，需 approval",
    "docker_compose_build": "執行 docker compose build，需 approval",
    "docker_compose_down": "執行 docker compose down，需 approval",
    "docker_compose_logs": "查看 docker compose logs",
    "docker_compose_ps": "查看 docker compose ps",
    "docker_compose_up": "執行 docker compose up -d，需 approval",
}

SKIPPED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".agentx",
    "__pycache__",
    "node_modules",
}

ALLOWED_COMMANDS = {
    "uv run ruff check .": ["uv", "run", "ruff", "check", "."],
    "uv run pytest -q": ["uv", "run", "pytest", "-q"],
    "git status --short --branch": ["git", "status", "--short", "--branch"],
    "git diff": ["git", "diff"],
}

DOCKER_COMPOSE_ACTIONS = {"ps", "build", "up", "down", "logs"}
DOCKER_COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
WEB_MAX_BYTES = 1_000_000


def docker_compose_command(
    workspace: Path,
    action: str,
    *,
    compose_file: str | None = None,
    service: str | None = None,
    tail: int = 100,
) -> list[str]:
    workspace = workspace.resolve()
    compose_path = resolve_compose_file(workspace, compose_file)
    command = ["docker", "compose", "-f", str(compose_path)]
    if action == "ps":
        return [*command, "ps"]
    if action == "build":
        return [*command, "build"]
    if action == "up":
        return [*command, "up", "-d"]
    if action == "down":
        return [*command, "down"]
    if action == "logs":
        safe_tail = max(1, min(int(tail), 1000))
        args = [*command, "logs", "--tail", str(safe_tail)]
        if service:
            args.append(service)
        return args
    raise ValueError(f"unsupported docker compose action: {action}")


def resolve_compose_file(workspace: Path, compose_file: str | None = None) -> Path:
    workspace = workspace.resolve()
    candidates = [compose_file] if compose_file else list(DOCKER_COMPOSE_FILES)
    for candidate in candidates:
        if not candidate:
            continue
        path = (workspace / candidate).resolve()
        if workspace != path and workspace not in path.parents:
            raise ValueError(f"compose file escapes workspace: {candidate}")
        if path.is_file():
            return path
    raise FileNotFoundError("compose.yaml / compose.yml / docker-compose.yml not found")


class TextExtractingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.parts)).strip()


def validate_external_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    if not parsed.hostname:
        raise ValueError("URL must include a host")
    host = parsed.hostname.lower()
    if host in {"localhost"} or host.endswith(".local"):
        raise ValueError("local hosts are blocked")
    for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = info[4][0]
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(f"blocked non-public address: {address}")
    return url.strip()


def extract_web_text(content: str, content_type: str = "") -> str:
    if "html" not in content_type.lower() and not re.search(r"<html|<body|<p\\b", content, re.I):
        return content.strip()
    parser = TextExtractingHTMLParser()
    parser.feed(content)
    return parser.text()


class ToolRegistry:
    def __init__(
        self,
        workspace: Path,
        memory: MemoryHallClient,
        approver: Callable[[str, dict[str, Any], Risk], bool] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.memory = memory
        self.approver = approver

    def describe_tools(self) -> dict[str, str]:
        return dict(TOOL_DESCRIPTIONS)

    def run(self, tool: str, args: dict[str, Any]) -> ToolResult:
        require_allowed(tool)
        risk = classify_tool(tool)
        if risk == Risk.YELLOW and self.approver is not None:
            if not self.approver(tool, args, risk):
                return ToolResult(tool=tool, ok=False, content=f"Rejected by approval gate: {tool}")
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

    def _tool_run_command(self, command: str) -> str:
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

    def _tool_web_fetch(self, url: str, max_chars: int = 20000) -> str:
        safe_url = validate_external_url(url)
        with httpx.Client(
            follow_redirects=True,
            timeout=20,
            headers={"User-Agent": "agentX/0.1 (+local engineering shell)"},
        ) as client:
            response = client.get(safe_url)
            response.raise_for_status()
        content = response.content[:WEB_MAX_BYTES].decode(
            response.encoding or "utf-8",
            errors="replace",
        )
        text = extract_web_text(content, response.headers.get("content-type", ""))
        if not text:
            text = f"[no extractable text from {safe_url}]"
        return f"URL: {response.url}\nStatus: {response.status_code}\n\n{text[:max_chars]}"

    def _tool_apply_patch(self, patch: str) -> str:
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

    def _tool_search_replace(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """精準字串替換，適合本地模型使用，比大範圍 patch 更可靠。"""
        target = self._resolve_inside_workspace(path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        content = target.read_text(encoding="utf-8", errors="replace")

        if old_string not in content:
            return f"未找到要替換的內容（old_string）\n檔案：{path}"

        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1

        target.write_text(new_content, encoding="utf-8")

        return (
            f"search_replace 成功\n"
            f"檔案：{path}\n"
            f"替換次數：{count}\n"
            f"replace_all：{replace_all}"
        )

    def _tool_insert_code(
        self,
        path: str,
        content: str,
        insert_after: str,
    ) -> str:
        """在指定文字後插入程式碼。適合新增函式、方法、import 等。"""
        target = self._resolve_inside_workspace(path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        file_content = target.read_text(encoding="utf-8", errors="replace")

        if insert_after not in file_content:
            return f"找不到插入基準點（insert_after）\n檔案：{path}"

        new_content = file_content.replace(insert_after, insert_after + content, 1)
        target.write_text(new_content, encoding="utf-8")

        return f"insert_code 成功\n檔案：{path}\n已插入內容於指定位置後方"

    def _tool_docker_compose_ps(self, compose_file: str | None = None) -> str:
        return self._run_docker_compose("ps", compose_file=compose_file)

    def _tool_docker_compose_build(self, compose_file: str | None = None) -> str:
        return self._run_docker_compose("build", compose_file=compose_file)

    def _tool_docker_compose_up(self, compose_file: str | None = None) -> str:
        return self._run_docker_compose("up", compose_file=compose_file)

    def _tool_docker_compose_down(self, compose_file: str | None = None) -> str:
        return self._run_docker_compose("down", compose_file=compose_file)

    def _tool_docker_compose_logs(
        self,
        compose_file: str | None = None,
        service: str | None = None,
        tail: int = 100,
    ) -> str:
        return self._run_docker_compose(
            "logs",
            compose_file=compose_file,
            service=service,
            tail=tail,
        )

    def _run_docker_compose(
        self,
        action: str,
        *,
        compose_file: str | None = None,
        service: str | None = None,
        tail: int = 100,
    ) -> str:
        command = self._docker_compose_command(
            action,
            compose_file=compose_file,
            service=service,
            tail=tail,
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

    def _docker_compose_command(
        self,
        action: str,
        *,
        compose_file: str | None = None,
        service: str | None = None,
        tail: int = 100,
    ) -> list[str]:
        return docker_compose_command(
            self.workspace,
            action,
            compose_file=compose_file,
            service=service,
            tail=tail,
        )

    def _resolve_compose_file(self, compose_file: str | None = None) -> Path:
        return resolve_compose_file(self.workspace, compose_file)

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
