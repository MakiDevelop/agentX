from pathlib import Path

from agentx.tools import ToolRegistry, builtin_tools


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return ""

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return ""


def test_run_command_rejects_non_allowlisted_command(tmp_path: Path) -> None:
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()))  # type: ignore[arg-type]
    result = registry.run("run_command", {"command": "echo hello"})

    assert not result.ok
    assert "not allowlisted" in result.content


def test_cargo_commands_in_allowlist() -> None:
    from agentx.tools._helpers import ALLOWED_COMMANDS

    for command in (
        "cargo check",
        "cargo build",
        "cargo test",
        "cargo fmt --check",
        "cargo clippy -- -D warnings",
    ):
        assert command in ALLOWED_COMMANDS
