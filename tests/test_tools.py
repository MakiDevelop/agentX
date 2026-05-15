from pathlib import Path

import pytest

from agentx.tools import ToolRegistry, builtin_tools, docker_compose_command


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


def _registry(tmp_path: Path) -> ToolRegistry:
    # Tests exercise YELLOW tools (write_file / edit_file) without a real
    # interactive approver — opt into auto-approve so N2 fail-closed
    # doesn't break the suite.
    return ToolRegistry(
        builtin_tools(tmp_path, FakeMemory()),  # type: ignore[arg-type]
        auto_approve_yellow=True,
    )


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


def test_write_file_creates_file(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": "hello.txt", "content": "hi"},
    )
    assert result.ok
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_write_file_creates_parent_dirs(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": "a/b/c.txt", "content": "x"},
    )
    assert result.ok
    assert (tmp_path / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "x"


def test_write_file_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": "out.txt", "content": "new"},
    )
    assert result.ok
    assert target.read_text(encoding="utf-8") == "new"


def test_write_file_rejects_workspace_escape(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": "../outside.txt", "content": "nope"},
    )
    assert not result.ok
    assert "escapes workspace" in result.content


def test_write_file_rejects_workspace_root(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run("write_file", {"path": "", "content": "nope"})
    assert not result.ok
    assert "workspace root" in result.content


def test_edit_file_applies_single_replacement(tmp_path: Path) -> None:
    target = tmp_path / "src.rs"
    target.write_text("fn main() { println!(\"hi\"); }", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "src.rs", "edits": [{"oldText": "\"hi\"", "newText": "\"world\""}]},
    )
    assert result.ok
    assert target.read_text(encoding="utf-8") == "fn main() { println!(\"world\"); }"


def test_edit_file_applies_multiple_edits_in_order(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("AAA BBB CCC", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {
            "path": "f.txt",
            "edits": [
                {"oldText": "AAA", "newText": "111"},
                {"oldText": "CCC", "newText": "333"},
            ],
        },
    )
    assert result.ok
    assert target.read_text(encoding="utf-8") == "111 BBB 333"


def test_edit_file_rejects_missing_old_text(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "f.txt", "edits": [{"oldText": "GONE", "newText": "x"}]},
    )
    assert not result.ok
    assert "找不到" in result.content


def test_edit_file_rejects_non_unique_old_text(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("foo foo foo", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "f.txt", "edits": [{"oldText": "foo", "newText": "bar"}]},
    )
    assert not result.ok
    assert "唯一" in result.content


def test_edit_file_rejects_empty_old_text(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "f.txt", "edits": [{"oldText": "", "newText": "x"}]},
    )
    assert not result.ok


def test_edit_file_rejects_missing_file(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "no-such.txt", "edits": [{"oldText": "x", "newText": "y"}]},
    )
    assert not result.ok


def test_write_file_rejects_dotgit(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": ".git/hooks/pre-commit", "content": "#!/bin/sh\nrm -rf /"},
    )
    assert not result.ok
    assert "protected location" in result.content
    assert ".git" in result.content


def test_write_file_rejects_dotagentx(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": ".agentx/config.toml", "content": "x"},
    )
    assert not result.ok
    assert "protected location" in result.content


def test_write_file_rejects_venv(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": ".venv/lib/python3.13/site-packages/evil.py", "content": "x"},
    )
    assert not result.ok
    assert "protected location" in result.content


def test_write_file_rejects_nested_protected_dir(tmp_path: Path) -> None:
    # Even if the protected component is deeper than the top level.
    registry = _registry(tmp_path)
    result = registry.run(
        "write_file",
        {"path": "src/__pycache__/x.pyc", "content": "x"},
    )
    assert not result.ok
    assert "protected location" in result.content


def test_edit_file_rejects_dotgit(tmp_path: Path) -> None:
    # Pre-create the file (bypassing the protection) then try edit_file.
    hook = tmp_path / ".git" / "hooks"
    hook.mkdir(parents=True)
    pre_commit = hook / "pre-commit"
    pre_commit.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {
            "path": ".git/hooks/pre-commit",
            "edits": [{"oldText": "echo hi", "newText": "rm -rf /"}],
        },
    )
    assert not result.ok
    assert "protected location" in result.content


def test_edit_file_accepts_legacy_single_pair(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("alpha", encoding="utf-8")
    registry = _registry(tmp_path)
    result = registry.run(
        "edit_file",
        {"path": "f.txt", "oldText": "alpha", "newText": "beta"},
    )
    assert result.ok
    assert target.read_text(encoding="utf-8") == "beta"
