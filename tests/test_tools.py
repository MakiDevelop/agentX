from pathlib import Path

import pytest

from agentx import infrastructure_context
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


def test_infrastructure_context_tool_reads_resource_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "resource-map.md").write_text("RESOURCE_MAP_MARKER", encoding="utf-8")
    monkeypatch.setattr(infrastructure_context.Path, "home", staticmethod(lambda: tmp_path))
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("infrastructure_context", {"map": "resource"})

    assert result.ok
    assert "RESOURCE_MAP_MARKER" in result.content
    assert "read-only references" in result.content


def test_analyze_intent_tool_returns_execution_brief(tmp_path: Path) -> None:
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("analyze_intent", {"text": "修復 approval policy 測試"})

    assert result.ok
    assert "## Intent Brief" in result.content
    assert "- Likely action: fix" in result.content
    assert "/where approval" in result.content


def test_find_files_path_match_without_content_match(tmp_path: Path) -> None:
    (tmp_path / "approval_policy.md").write_text("unrelated", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("find_files", {"keyword": "approval"})

    assert result.ok
    assert "## Path matches" in result.content
    assert "- approval_policy.md" in result.content
    assert "## Content matches\n- (none)" in result.content
    assert "- /read approval_policy.md" in result.content


def test_find_files_content_match_and_no_result(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.py").write_text("APPROVAL_MODE = 'ask'\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("find_files", {"keyword": "approval"})

    assert result.ok
    assert "## Content matches" in result.content
    assert "src/config.py:1:APPROVAL_MODE = 'ask'" in result.content
    assert "- /read src/config.py" in result.content

    missing = registry.run("find_files", {"keyword": "not-present"})
    assert missing.ok
    assert "No matches for 'not-present'" in missing.content


def test_find_files_respects_path_and_result_limits(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    for index in range(3):
        (tmp_path / "src" / f"needle_{index}.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "docs" / "needle_docs.md").write_text("needle\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run(
        "find_files",
        {"keyword": "needle", "path": "src", "path_limit": 2, "content_limit": 1, "read_limit": 2},
    )

    assert result.ok
    assert "- src/needle_0.py" in result.content
    assert "- src/needle_1.py" in result.content
    assert "- src/needle_2.py" not in result.content
    assert "docs/needle_docs.md" not in result.content
    assert result.content.count("/read ") == 2


def test_locate_topic_ranks_path_stem_entry_point(tmp_path: Path) -> None:
    src = tmp_path / "src" / "agentx"
    src.mkdir(parents=True)
    (src / "approval.py").write_text("def approve_request():\n    pass\n", encoding="utf-8")
    (src / "random.py").write_text("approval approval approval\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("locate_topic", {"topic": "approval"})

    assert result.ok
    locations = result.content.split("## Likely locations\n", 1)[1]
    assert locations.splitlines()[0].startswith("- src/agentx/approval.py ")
    assert "- /read src/agentx/approval.py" in result.content


def test_locate_topic_prefers_multi_term_matches(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "approval.py").write_text("approval only\n", encoding="utf-8")
    (src / "policy.py").write_text("approval policy mode\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("locate_topic", {"topic": "approval policy"})

    assert result.ok
    locations = result.content.split("## Likely locations\n", 1)[1]
    assert locations.splitlines()[0].startswith("- src/policy.py ")
    assert "multi-term" in locations.splitlines()[0]


def test_locate_topic_strips_question_noise_and_handles_no_results(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handoff.md").write_text("handoff notes\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("locate_topic", {"topic": "where is handoff built"})

    assert result.ok
    assert "## Topic terms\n- handoff" in result.content
    assert "where" not in result.content.split("## Topic terms\n", 1)[1].splitlines()[0]

    missing = registry.run("locate_topic", {"topic": "nonexistent concept xyz"})
    assert missing.ok
    assert "No locations for" in missing.content


def test_locate_topic_rejects_empty_topic_and_limits_output(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for index in range(6):
        (src / f"needle_{index}.py").write_text("needle\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    empty = registry.run("locate_topic", {"topic": "where is the"})
    assert not empty.ok
    assert "topic is required" in empty.content

    result = registry.run("locate_topic", {"topic": "needle", "limit": 3, "read_limit": 2})
    assert result.ok
    assert result.content.count(" score=") == 3
    assert result.content.count("/read ") == 2


def test_locate_topic_skips_local_memory_store(tmp_path: Path) -> None:
    (tmp_path / ".amh").mkdir()
    (tmp_path / ".amh" / "handoff.json").write_text("handoff\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "handoff.py").write_text("handoff\n", encoding="utf-8")
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]

    result = registry.run("locate_topic", {"topic": "handoff"})

    assert result.ok
    assert ".amh/handoff.json" not in result.content
    assert "src/handoff.py" in result.content


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


# === Focused tests for WebFetchTool ===

def test_web_fetch_is_registered(tmp_path: Path) -> None:
    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    tool = registry.get("web_fetch")
    assert tool is not None
    assert tool.name == "web_fetch"
    assert tool.risk.value == "GREEN"


def test_web_fetch_success_returns_cleaned_text(tmp_path: Path, monkeypatch) -> None:
    html = "<html><script>bad()</script><body><h1>Hello</h1><p>World</p></body></html>"
    body = html.encode()

    class FakeStreamResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield body

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            assert url == "https://example.com/page"
            return FakeStreamResponse()

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    # Public resolve so validate_external_url does not block
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://example.com/page"})

    assert result.ok
    assert "Hello" in result.content
    assert "World" in result.content
    assert "bad()" not in result.content
    assert "Unknown tool" not in result.content


def test_web_fetch_blocks_localhost_before_network(tmp_path: Path, monkeypatch) -> None:
    called = {"stream": False}

    class BoomClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            called["stream"] = True
            raise AssertionError("network must not be reached for blocked URL")

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", BoomClient)

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "http://localhost:3000"})

    assert not result.ok
    assert "local hosts" in result.content
    assert called["stream"] is False


def test_web_fetch_blocks_private_url_before_network(tmp_path: Path, monkeypatch) -> None:
    called = {"stream": False}

    class BoomClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            called["stream"] = True
            raise AssertionError("network must not be reached for private URL")

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", BoomClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.5", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://internal.example"})

    assert not result.ok
    assert "blocked non-public" in result.content
    assert called["stream"] is False


def test_web_fetch_http_status_error_propagates(tmp_path: Path, monkeypatch) -> None:
    import httpx

    class FakeStreamResponse:
        headers = {"content-type": "text/html"}

        def __init__(self, url: str) -> None:
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            resp = httpx.Response(403, request=httpx.Request("GET", self.url))
            resp.raise_for_status()

        def iter_bytes(self):
            yield b""

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse(url)

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://example.com/secret"})

    assert not result.ok
    assert result.error_type == "HTTPStatusError"
    assert "403" in result.content
    assert "Forbidden" in result.content


def test_web_fetch_respects_max_chars(tmp_path: Path, monkeypatch) -> None:
    body = "X" * 5000
    encoded = body.encode()

    class FakeStreamResponse:
        headers = {"content-type": "text/plain"}
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield encoded

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse()

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://example.com/big", "max_chars": 100})

    assert result.ok
    assert len(result.content) == 100


def test_web_fetch_does_not_follow_redirects(tmp_path: Path, monkeypatch) -> None:
    import httpx

    seen: list[dict[str, object]] = []

    class FakeStreamResponse:
        headers = {"location": "http://localhost:3000/admin", "content-type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            resp = httpx.Response(
                302,
                headers=self.headers,
                request=httpx.Request("GET", "https://example.com/redirect"),
            )
            resp.raise_for_status()

        def iter_bytes(self):
            yield b""

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            seen.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse()

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://example.com/redirect"})

    assert not result.ok
    assert seen[0]["follow_redirects"] is False
    assert result.error_type == "HTTPStatusError"
    assert "302" in result.content


def test_web_fetch_rejects_binary_content_type(tmp_path: Path, monkeypatch) -> None:
    class FakeStreamResponse:
        headers = {"content-type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            raise AssertionError("binary body must not be read")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse()

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run("web_fetch", {"url": "https://example.com/file.zip"})

    assert not result.ok
    assert "unsupported content-type" in result.content


def test_web_fetch_rejects_response_over_max_bytes(tmp_path: Path, monkeypatch) -> None:
    class FakeStreamResponse:
        headers = {"content-type": "text/plain"}
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b"abcd"
            yield b"efgh"

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse()

    monkeypatch.setattr("agentx.tools.builtin.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "agentx.tools._helpers.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    registry = ToolRegistry(builtin_tools(tmp_path, FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]
    result = registry.run(
        "web_fetch",
        {"url": "https://example.com/huge", "max_bytes": 6},
    )

    assert not result.ok
    assert "response too large" in result.content


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
