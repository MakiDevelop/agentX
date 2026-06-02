from pathlib import Path

import pytest

from agentx.tools import ToolRegistry, docker_compose_command, extract_web_text, validate_external_url


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


def test_run_command_prints_final_command_and_args(tmp_path: Path) -> None:
    registry = ToolRegistry(workspace=tmp_path, memory=FakeMemory())  # type: ignore[arg-type]
    result = registry.run("run_command", {"command": "git status --short --branch"})

    assert result.ok
    assert "final command:" in result.content
    assert "args:" in result.content
    assert "0: git" in result.content


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


def test_extract_web_text_strips_scripts_and_tags() -> None:
    html = "<html><script>bad()</script><body><h1>Hello</h1><p>World</p></body></html>"

    text = extract_web_text(html, "text/html")

    assert "Hello" in text
    assert "World" in text
    assert "bad()" not in text


def test_validate_external_url_rejects_localhost() -> None:
    with pytest.raises(ValueError, match="local hosts"):
        validate_external_url("http://localhost:3000")


def test_web_fetch_blocks_private_network(monkeypatch) -> None:
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("192.168.1.1", 80))],
    )

    with pytest.raises(ValueError, match="blocked non-public"):
        validate_external_url("https://example.test")
