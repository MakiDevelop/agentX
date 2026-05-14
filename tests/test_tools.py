from pathlib import Path

from agentx.tools import ToolRegistry


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


def test_read_file_blocks_workspace_escape(tmp_path: Path) -> None:
    registry = ToolRegistry(workspace=tmp_path, memory=FakeMemory())  # type: ignore[arg-type]
    result = registry.run("read_file", {"path": "../outside.txt"})
    assert not result.ok
    assert "escapes workspace" in result.content


def test_list_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry(workspace=tmp_path, memory=FakeMemory())  # type: ignore[arg-type]
    result = registry.run("list_files", {})
    assert result.ok
    assert result.content == "a.txt"
