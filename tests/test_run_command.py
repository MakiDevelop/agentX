from pathlib import Path

from agentx.tools import ToolRegistry, builtin_tools


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return ""

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return ""


def _registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        builtin_tools(tmp_path, FakeMemory()),  # type: ignore[arg-type]
        auto_approve_yellow=True,
    )


def test_run_command_rejects_non_allowlisted_command(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run("run_command", {"command": "echo hello"})

    assert not result.ok
    assert "not allowlisted" in result.content


def test_run_command_keeps_only_safe_cargo_command_in_green_allowlist() -> None:
    from agentx.tools._helpers import ALLOWED_COMMANDS, BUILD_COMMANDS

    # cargo fmt --check stays GREEN (pure parser, no build.rs).
    assert "cargo fmt --check" in ALLOWED_COMMANDS

    # Build/test cargo commands moved to YELLOW BUILD_COMMANDS.
    for command in ("cargo check", "cargo build", "cargo test", "cargo clippy -- -D warnings"):
        assert command not in ALLOWED_COMMANDS
        assert command in BUILD_COMMANDS


def test_run_command_rejects_build_command_in_green_path(tmp_path: Path) -> None:
    # cargo build is now YELLOW; trying it through run_command should be rejected.
    registry = _registry(tmp_path)
    result = registry.run("run_command", {"command": "cargo build"})

    assert not result.ok
    assert "not allowlisted" in result.content


def test_run_build_command_rejects_non_build_command(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run("run_build_command", {"command": "echo hi"})

    assert not result.ok
    assert "not allowlisted" in result.content


def test_run_build_command_rejects_green_command(tmp_path: Path) -> None:
    # ruff check is GREEN; should not route through run_build_command either.
    registry = _registry(tmp_path)
    result = registry.run("run_build_command", {"command": "uv run ruff check ."})

    assert not result.ok
    assert "not allowlisted" in result.content


def test_run_build_command_requires_approval_by_default(tmp_path: Path) -> None:
    # Without approver or auto_approve_yellow, run_build_command (YELLOW) is blocked.
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()))  # type: ignore[arg-type]
    result = registry.run("run_build_command", {"command": "cargo check"})

    assert not result.ok
    assert "approver" in result.content or "approval" in result.content.lower()
