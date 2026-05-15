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
