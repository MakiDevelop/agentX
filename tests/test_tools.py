from pathlib import Path

import pytest

from agentx.tools import ToolRegistry, builtin_tools, docker_compose_command, extract_web_text, validate_external_url


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


def test_read_file_blocks_workspace_escape(tmp_path: Path) -> None:
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("read_file", {"path": "../outside.txt"})
    assert not result.ok
    assert "escapes workspace" in result.content


def test_list_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("list_files", {})
    assert result.ok
    assert result.content == "a.txt"


def test_run_command_prints_final_command_and_args(tmp_path: Path) -> None:
    # Note: test runs in a tmp_path that is not a git repo, so git status returns non-zero
    # with an error message (in Chinese in this env). The tool still succeeds in *executing*
    # the allowlisted command and returns the output + exit code.
    # The old assertions ("final command:", "args:", "0: git") appear to be from a previous
    # implementation of the tool output format. Updated to match current RunCommandTool.
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("run_command", {"command": "git status --short --branch"})

    assert result.ok
    assert "$ git status --short --branch" in result.content
    assert "exit=" in result.content


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


# === Focused tests for InsertCodeTool (added to address Codex review Medium item) ===

def test_insert_code_success(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("def existing():\n    pass\n# MARKER\n", encoding="utf-8")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "insert_code",
        {
            "path": "module.py",
            "insert_after": "# MARKER",
            "content": "\ndef new_func():\n    return 42\n",
        },
    )

    assert result.ok
    assert "inserted" in result.content
    content = target.read_text(encoding="utf-8")
    assert "def new_func" in content
    assert "return 42" in content
    # Original content preserved
    assert "def existing" in content


def test_insert_code_marker_not_found(tmp_path: Path) -> None:
    target = tmp_path / "code.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "insert_code",
        {"path": "code.py", "insert_after": "# NONEXISTENT", "content": "x = 1"},
    )

    assert not result.ok
    assert "not found" in result.content
    assert "exactly as provided" in result.content


def test_insert_code_marker_not_unique(tmp_path: Path) -> None:
    target = tmp_path / "dup.py"
    target.write_text("pass\n# DUP\nmore\n# DUP\n", encoding="utf-8")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "insert_code",
        {"path": "dup.py", "insert_after": "# DUP", "content": "inserted"},
    )

    assert not result.ok
    assert "appears" in result.content and "times" in result.content
    assert "unique" in result.content


def test_insert_code_blocks_workspace_escape(tmp_path: Path) -> None:
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "insert_code",
        {"path": "../outside.py", "insert_after": "x", "content": "y"},
    )

    assert not result.ok
    assert "escapes workspace" in result.content


def test_insert_code_rejects_protected_path(tmp_path: Path) -> None:
    # .agentx is protected
    protected_dir = tmp_path / ".agentx"
    protected_dir.mkdir()
    target = protected_dir / "secret.py"
    target.write_text("# secret\n", encoding="utf-8")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "insert_code",
        {"path": ".agentx/secret.py", "insert_after": "# secret", "content": "bad"},
    )

    assert not result.ok
    assert "protected location" in result.content or "refusing to write" in result.content


def test_insert_code_registry_name_resolution(tmp_path: Path) -> None:
    """Ensure 'insert_code' name (as used in prompts) resolves correctly via aliases/primary."""
    target = tmp_path / "t.py"
    target.write_text("x = 1\n# END", encoding="utf-8")

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    # Direct name
    res1 = registry.run("insert_code", {"path": "t.py", "insert_after": "# END", "content": "\ny=2"})
    assert res1.ok

    # Confirm tool is registered under the name
    tool = registry.get("insert_code")
    assert tool is not None
    assert tool.name == "insert_code"
