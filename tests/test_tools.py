from pathlib import Path

import pytest

from agentx.tools import ToolRegistry, builtin_tools, docker_compose_command


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


def _registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(builtin_tools(tmp_path, FakeMemory()))  # type: ignore[arg-type]


def test_read_file_blocks_workspace_escape(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run("read_file", {"path": "../outside.txt"})
    assert not result.ok
    assert "escapes workspace" in result.content


def test_list_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run("list_files", {})
    assert result.ok
    assert result.content == "a.txt"


def test_docker_compose_command_uses_workspace_compose(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")

    command = docker_compose_command(tmp_path, "up")

    assert command == ["docker", "compose", "-f", str(compose), "up", "-d"]


def test_docker_compose_logs_command_with_service(tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    command = docker_compose_command(tmp_path, "logs", service="web", tail=2000)

    assert command == ["docker", "compose", "-f", str(compose), "logs", "--tail", "1000", "web"]


def test_docker_compose_command_rejects_missing_compose(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        docker_compose_command(tmp_path, "ps")


def test_docker_compose_command_rejects_workspace_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "compose.yaml"
    outside.write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        docker_compose_command(tmp_path, "ps", compose_file="../compose.yaml")
