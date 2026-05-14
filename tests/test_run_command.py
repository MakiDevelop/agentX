from pathlib import Path

from agentx.tools import ToolRegistry


class FakeMemory:
    pass


def test_run_command_rejects_non_allowlisted_command(tmp_path: Path) -> None:
    registry = ToolRegistry(workspace=tmp_path, memory=FakeMemory())  # type: ignore[arg-type]
    result = registry.run("run_command", {"command": "echo hello"})

    assert not result.ok
    assert "not allowlisted" in result.content
