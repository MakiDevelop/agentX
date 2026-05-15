from __future__ import annotations

import subprocess
from pathlib import Path


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

ALLOWED_COMMANDS: dict[str, list[str]] = {
    "uv run ruff check .": ["uv", "run", "ruff", "check", "."],
    "uv run pytest -q": ["uv", "run", "pytest", "-q"],
    "git status --short --branch": ["git", "status", "--short", "--branch"],
    "git diff": ["git", "diff"],
}

DOCKER_COMPOSE_ACTIONS = {"ps", "build", "up", "down", "logs"}
DOCKER_COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


def resolve_inside_workspace(workspace: Path, path: str | None) -> Path:
    target = workspace if path in (None, "") else (workspace / path).resolve()
    if workspace != target and workspace not in target.parents:
        raise ValueError(f"Path escapes workspace: {path}")
    return target


def run_subprocess(
    cmd: list[str],
    cwd: Path,
    timeout: float = 20.0,
) -> tuple[int, str]:
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout or completed.stderr
    return completed.returncode, output


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
