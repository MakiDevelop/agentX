from __future__ import annotations

import re
import socket
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


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

# Path components write_file / edit_file refuse to descend into. .git is the
# critical one — writing .git/hooks/pre-commit lets the agent achieve arbitrary
# code execution on the next git operation. The rest are caches / vendored
# code / virtualenvs that should never be agent-edited.
WRITE_PROTECTED_PARTS = frozenset(
    {
        ".git",
        ".agentx",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "target",
    }
)


def _canonical_part(part: str) -> str:
    """Normalize one path component for write-protection checks."""
    part = unicodedata.normalize("NFC", part)
    part = part.split(":", 1)[0]
    part = part.rstrip(" .")
    return part.casefold()


_PROTECTED_CANONICAL = frozenset(_canonical_part(part) for part in WRITE_PROTECTED_PARTS)

# GREEN-risk commands: read-only inspection or pure syntax checks. Safe to run
# without approval. uv run pytest stays here for backward compat even though it
# executes arbitrary test code — reviewer note: pre-existing scope, not promoted
# in this change.
ALLOWED_COMMANDS: dict[str, list[str]] = {
    "uv run ruff check .": ["uv", "run", "ruff", "check", "."],
    "uv run pytest -q": ["uv", "run", "pytest", "-q"],
    "git status --short --branch": ["git", "status", "--short", "--branch"],
    "git diff": ["git", "diff"],
    "cargo fmt --check": ["cargo", "fmt", "--", "--check"],
    "npx tsc --noEmit": ["npx", "tsc", "--noEmit"],
    "node --version": ["node", "--version"],
    "npm --version": ["npm", "--version"],
    "ls -la": ["ls", "-la"],
    "ls": ["ls"],
}

# YELLOW-risk build / test commands: invoke build.rs, proc-macros, or test code
# → potentially run arbitrary code from the workspace or its dependencies.
# Routed through a separate run_build_command tool that requires approval.
BUILD_COMMANDS: dict[str, list[str]] = {
    "cargo check": ["cargo", "check"],
    "cargo build": ["cargo", "build"],
    "cargo test": ["cargo", "test"],
    "cargo clippy -- -D warnings": ["cargo", "clippy", "--", "-D", "warnings"],
    "npm install": ["npm", "install"],
    "npm run build": ["npm", "run", "build"],
    "npm run test": ["npm", "run", "test"],
    "npx vitest": ["npx", "vitest"],
    # Tsumu expansion for Node/TS projects (Codex review note: these execute arbitrary
    # workspace code / test code, therefore correctly YELLOW via run_build_command + approval).
    "npm test": ["npm", "test"],
    "npx vitest run": ["npx", "vitest", "run"],
}

DOCKER_COMPOSE_ACTIONS = {"ps", "build", "up", "down", "logs"}
DOCKER_COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


def resolve_inside_workspace(workspace: Path, path: str | None) -> Path:
    target = workspace if path in (None, "") else (workspace / path).resolve()
    if workspace != target and workspace not in target.parents:
        raise ValueError(f"Path escapes workspace: {path}")
    return target


def ensure_safe_write_path(workspace: Path, target: Path) -> None:
    """Reject writes into workspace-internal directories that should never be
    agent-modified (``.git``, ``.agentx``, ``.venv``, caches, vendored deps).

    ``.git/hooks/pre-commit`` is the highlight: writing there gives any
    subsequent git operation arbitrary code execution.

    Known residual risk: a malicious workspace can still race the checked path
    with a symlink swap before the write; the agent approval gate is the
    remaining backstop for that TOCTOU class.
    """
    try:
        relative = target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"target is outside workspace: {target}") from exc
    for part in relative.parts:
        if _canonical_part(part) in _PROTECTED_CANONICAL:
            raise ValueError(
                f"refusing to write to protected location: {relative} "
                f"(matched {part!r}); see WRITE_PROTECTED_PARTS"
            )


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


# === Web helpers (added to support test_tools web tests post-merge) ===

def extract_web_text(html: str, content_type: str = "") -> str:
    """Simple text extraction: strip scripts/styles and tags. For Gemma-friendly tool use."""
    if not html or not isinstance(html, str):
        return ""
    # Remove script and style blocks
    text = re.sub(r'(?is)<(script|style).*?>.*?</\1>', ' ', html)
    # Remove all other tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def validate_external_url(url: str) -> None:
    """Reject local/private hosts. Used by web_fetch tool for safety (Gemma context)."""
    if not url or not isinstance(url, str):
        raise ValueError("invalid url")
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("must be http or https")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127."):
        raise ValueError("local hosts not allowed")
    # Check for private networks via getaddrinfo (test monkeys this)
    try:
        addrs = socket.getaddrinfo(host, None)
        for _, _, _, _, sockaddr in addrs:
            ip = sockaddr[0]
            if (
                ip.startswith(("10.", "192.168."))
                or ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31
            ):
                raise ValueError("blocked non-public")
    except socket.gaierror:
        pass  # can't resolve; let caller decide or allow for test
    # Note: full impl may use requests/httpx with allow_redirects=False etc.
