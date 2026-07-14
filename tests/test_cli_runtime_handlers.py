"""Coverage for runtime slash handlers used by run_shell() nested handlers.

These tests exercise ``agentx.cli_runtime_handlers`` — the real interactive
logic for /plan, /execute, /mode, /files, /read, /find, /grep, /search, /git, /diff,
low-risk tool-backed /memory, /fetch, /run, /test, low-risk inspection
handlers /status, /sessions, /jobs, /task readonly, and pure info/display
handlers /help, /guide, /workflows, /tools, /context, /history,
/transcript — not the simplified ``cli_slash_shims``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentx.cli import ShellState, format_plan_status
from agentx.cli_runtime_handlers import (
    EXECUTE_SYSTEM_MESSAGE,
    handle_context,
    handle_diff,
    handle_execute,
    handle_fetch,
    handle_find,
    handle_files,
    handle_git,
    handle_grep,
    handle_guide,
    handle_help,
    handle_history,
    handle_jobs,
    handle_memory,
    handle_mode,
    handle_plan,
    handle_read,
    handle_run,
    handle_search,
    handle_sessions,
    handle_status,
    handle_stage,
    handle_task_readonly,
    handle_test,
    handle_tools,
    handle_transcript,
    handle_unstage,
    handle_workflows,
)
from agentx.protocol import ToolResult
from helpers import make_settings


@dataclass
class FakeTranscript:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    path: Path = field(default_factory=lambda: Path("/tmp/fake-transcript.jsonl"))

    def write(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


@dataclass
class FakeAgentSession:
    plan_only: bool = False
    messages: list[dict[str, str]] = field(default_factory=list)
    context_chars: int = 0


@dataclass
class FakeTools:
    """Records tools.run calls and returns a canned ToolResult."""

    result: ToolResult
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def run(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((name, args))
        return self.result


def _state(
    tmp_path: Path,
    *,
    plan_mode: bool = False,
    mode: str = "chat",
    with_session: bool = True,
    plan_only: bool | None = None,
) -> ShellState:
    state = ShellState(
        settings=make_settings(tmp_path),
        namespace="project:test",
        mode=mode,
        plan_mode=plan_mode,
    )
    if with_session:
        session = FakeAgentSession(
            plan_only=plan_mode if plan_only is None else plan_only,
        )
        state.agent_session = session  # type: ignore[assignment]
    else:
        state.agent_session = None
    return state


def _capture() -> tuple[list[str], Any]:
    lines: list[str] = []

    def emit(msg: str) -> None:
        lines.append(str(msg))

    return lines, emit


# --- /plan -----------------------------------------------------------------


def test_handle_plan_toggles_on_and_syncs_session(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=False)
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_plan(
        state,
        "/plan",
        transcript=transcript,
        emit=emit,
        format_status=format_plan_status,
    )

    assert state.plan_mode is True
    assert state.agent_session is not None
    assert state.agent_session.plan_only is True
    assert lines == [f"plan mode: {format_plan_status(True)}"]
    assert transcript.events == [("slash_command", {"command": "/plan", "plan": True})]


def test_handle_plan_toggles_off(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=True)
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_plan(
        state,
        "/plan",
        transcript=transcript,
        emit=emit,
        format_status=format_plan_status,
    )

    assert state.plan_mode is False
    assert state.agent_session is not None
    assert state.agent_session.plan_only is False
    assert lines == [f"plan mode: {format_plan_status(False)}"]
    assert transcript.events == [("slash_command", {"command": "/plan", "plan": False})]


# --- /execute --------------------------------------------------------------


def test_handle_execute_rejects_when_not_in_plan_mode(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=False, plan_only=False)
    transcript = FakeTranscript()
    chat_messages: list[dict[str, str]] = []
    lines, emit = _capture()

    handle_execute(
        state,
        "/execute",
        transcript=transcript,
        chat_messages=chat_messages,
        emit=emit,
    )

    assert state.plan_mode is False
    assert state.mode == "chat"
    assert chat_messages == []
    assert transcript.events == []
    assert lines == ["目前不在 plan 模式中"]


def test_handle_execute_from_plan_mode_switches_to_agent(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=True, mode="chat")
    transcript = FakeTranscript()
    chat_messages: list[dict[str, str]] = [{"role": "user", "content": "plan this"}]
    lines, emit = _capture()

    handle_execute(
        state,
        "/execute",
        transcript=transcript,
        chat_messages=chat_messages,
        emit=emit,
    )

    assert state.plan_mode is False
    assert state.agent_session is not None
    assert state.agent_session.plan_only is False
    assert state.mode == "agent"
    assert chat_messages[-1] == {"role": "system", "content": EXECUTE_SYSTEM_MESSAGE}
    assert state.agent_session.messages[-1] == {
        "role": "system",
        "content": EXECUTE_SYSTEM_MESSAGE,
    }
    assert transcript.events == [
        (
            "slash_command",
            {"command": "/execute", "plan": False, "mode": "agent", "action": "execute"},
        )
    ]
    assert lines == ["已切換至執行模式（mode=agent）。後續提示將可使用工具實際執行方案。"]


def test_handle_execute_keeps_agent_mode(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=True, mode="agent")
    transcript = FakeTranscript()
    chat_messages: list[dict[str, str]] = []
    lines, emit = _capture()

    handle_execute(
        state,
        "/execute",
        transcript=transcript,
        chat_messages=chat_messages,
        emit=emit,
    )

    assert state.mode == "agent"
    assert transcript.events[0][1]["mode"] == "agent"
    assert "mode=agent" in lines[0]


def test_handle_execute_accepts_session_plan_only_without_state_flag(tmp_path: Path) -> None:
    """Cover the OR branch: agent_session.plan_only True even if state.plan_mode False."""
    state = _state(tmp_path, plan_mode=False, mode="chat", plan_only=True)
    transcript = FakeTranscript()
    chat_messages: list[dict[str, str]] = []
    lines, emit = _capture()

    handle_execute(
        state,
        "/execute",
        transcript=transcript,
        chat_messages=chat_messages,
        emit=emit,
    )

    assert state.plan_mode is False
    assert state.mode == "agent"
    assert chat_messages[-1]["content"] == EXECUTE_SYSTEM_MESSAGE
    assert len(lines) == 1
    assert "執行模式" in lines[0]


def test_handle_execute_without_agent_session_still_updates_chat(tmp_path: Path) -> None:
    state = _state(tmp_path, plan_mode=True, mode="chat", with_session=False)
    transcript = FakeTranscript()
    chat_messages: list[dict[str, str]] = []
    lines, emit = _capture()

    handle_execute(
        state,
        "/execute",
        transcript=transcript,
        chat_messages=chat_messages,
        emit=emit,
    )

    assert state.plan_mode is False
    assert state.mode == "agent"
    assert chat_messages == [{"role": "system", "content": EXECUTE_SYSTEM_MESSAGE}]
    assert len(lines) == 1


# --- /mode -----------------------------------------------------------------


def test_handle_mode_switches_to_agent(tmp_path: Path) -> None:
    state = _state(tmp_path, mode="chat")
    transcript = FakeTranscript()
    lines, emit = _capture()
    errors: list[str] = []

    handle_mode(
        state,
        "/mode agent",
        transcript=transcript,
        emit=emit,
        emit_error=errors.append,
    )

    assert state.mode == "agent"
    assert lines == ["mode=agent"]
    assert errors == []
    assert transcript.events == [("slash_command", {"command": "/mode agent", "mode": "agent"})]


def test_handle_mode_ask_aliases_to_agent(tmp_path: Path) -> None:
    state = _state(tmp_path, mode="chat")
    transcript = FakeTranscript()
    lines, emit = _capture()
    errors: list[str] = []

    handle_mode(
        state,
        "/mode ask",
        transcript=transcript,
        emit=emit,
        emit_error=errors.append,
    )

    assert state.mode == "agent"
    assert lines == ["mode=agent"]
    assert errors == []


def test_handle_mode_rejects_invalid(tmp_path: Path) -> None:
    state = _state(tmp_path, mode="chat")
    transcript = FakeTranscript()
    lines, emit = _capture()
    errors: list[str] = []

    handle_mode(
        state,
        "/mode bogus",
        transcript=transcript,
        emit=emit,
        emit_error=errors.append,
    )

    assert state.mode == "chat"
    assert lines == []
    assert errors == ["mode must be chat, ask, or agent"]
    assert transcript.events == []


# --- /files /read /search /git /diff (read-only tool-backed) ---------------


def test_handle_files_defaults_path_to_dot() -> None:
    tools = FakeTools(ToolResult(tool="list_files", ok=True, content="a.py\nb.py"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_files("/files", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("list_files", {"path": "."})]
    assert lines == ["a.py\nb.py"]
    assert transcript.events == [
        ("tool", {"command": "/files", "ok": True, "content": "a.py\nb.py"})
    ]


def test_handle_files_accepts_path_and_emits_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="list_files", ok=False, content="not found"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_files("/files src", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("list_files", {"path": "src"})]
    assert lines == ["工具執行失敗：not found"]
    assert transcript.events == [
        ("tool", {"command": "/files", "ok": False, "content": "not found"})
    ]


def test_handle_read_includes_path_in_transcript() -> None:
    tools = FakeTools(ToolResult(tool="read_file", ok=True, content="hello"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_read("/read README.md", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("read_file", {"path": "README.md"})]
    assert lines == ["hello"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/read",
                "path": "README.md",
                "ok": True,
                "content": "hello",
            },
        )
    ]


def test_handle_read_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="read_file", ok=False, content="missing"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_read("/read no-such.py", tools=tools, transcript=transcript, emit=emit)

    assert lines == ["讀取失敗：missing"]
    assert transcript.events[0][1]["ok"] is False
    assert transcript.events[0][1]["path"] == "no-such.py"


def test_handle_search_success_and_failure() -> None:
    tools = FakeTools(ToolResult(tool="search_text", ok=True, content="src/a.py:1:hit"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_search("/search foo", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("search_text", {"pattern": "foo"})]
    # Historical payload: no pattern field in transcript
    assert transcript.events == [
        ("tool", {"command": "/search", "ok": True, "content": "src/a.py:1:hit"})
    ]
    assert lines == ["src/a.py:1:hit"]

    tools_fail = FakeTools(ToolResult(tool="search_text", ok=False, content="bad regex"))
    transcript_fail = FakeTranscript()
    fail_lines, fail_emit = _capture()
    handle_search("/search [", tools=tools_fail, transcript=transcript_fail, emit=fail_emit)
    assert fail_lines == ["搜尋失敗：bad regex"]


def test_handle_find_includes_keyword_in_transcript() -> None:
    tools = FakeTools(ToolResult(tool="find_files", ok=True, content="## Path matches\n- src/a.py"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_find("/find approval", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("find_files", {"keyword": "approval"})]
    assert lines == ["## Path matches\n- src/a.py"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/find",
                "keyword": "approval",
                "ok": True,
                "content": "## Path matches\n- src/a.py",
            },
        )
    ]


def test_handle_find_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="find_files", ok=False, content="keyword is required"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_find("/find ", tools=tools, transcript=transcript, emit=emit)

    assert lines == ["檢索失敗：keyword is required"]


def test_handle_grep_uses_search_text_with_optional_path() -> None:
    tools = FakeTools(ToolResult(tool="search_text", ok=True, content="src/a.py:1:needle"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_grep("/grep needle src", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("search_text", {"pattern": "needle", "path": "src"})]
    assert lines == ["src/a.py:1:needle"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/grep",
                "pattern": "needle",
                "path": "src",
                "ok": True,
                "content": "src/a.py:1:needle",
            },
        )
    ]


def test_handle_grep_defaults_path_and_reports_parse_error() -> None:
    tools = FakeTools(ToolResult(tool="search_text", ok=True, content="a.py:1:needle"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_grep('/grep "needle phrase"', tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("search_text", {"pattern": "needle phrase", "path": "."})]
    assert lines == ["a.py:1:needle"]

    bad_transcript = FakeTranscript()
    bad_lines, bad_emit = _capture()
    handle_grep('/grep "unterminated', tools=tools, transcript=bad_transcript, emit=bad_emit)

    assert bad_lines == ["搜尋失敗：No closing quotation"]
    assert bad_transcript.events == [
        ("tool", {"command": "/grep", "ok": False, "content": "No closing quotation"})
    ]


def test_handle_git_ignores_prompt_args() -> None:
    tools = FakeTools(ToolResult(tool="git_status", ok=True, content="## main"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_git("/git anything", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("git_status", {})]
    assert lines == ["## main"]
    assert transcript.events == [
        ("tool", {"command": "/git", "ok": True, "content": "## main"})
    ]


def test_handle_git_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="git_status", ok=False, content="not a repo"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_git("/git", tools=tools, transcript=transcript, emit=emit)

    assert lines == ["工具執行失敗：not a repo"]


def test_handle_stage_dispatches_paths_and_parse_error() -> None:
    tools = FakeTools(ToolResult(tool="git_stage", ok=True, content="$ git add -- a.py"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_stage('/stage "a file.py" src/b.py', tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("git_stage", {"paths": ["a file.py", "src/b.py"]})]
    assert lines == ["$ git add -- a.py"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/stage",
                "paths": ["a file.py", "src/b.py"],
                "ok": True,
                "content": "$ git add -- a.py",
            },
        )
    ]

    bad_transcript = FakeTranscript()
    bad_lines, bad_emit = _capture()
    handle_stage('/stage "unterminated', tools=tools, transcript=bad_transcript, emit=bad_emit)

    assert bad_lines == ["stage failed: No closing quotation"]
    assert bad_transcript.events == [
        ("tool", {"command": "/stage", "ok": False, "content": "No closing quotation"})
    ]


def test_handle_unstage_dispatches_paths_and_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="git_unstage", ok=False, content="broad git path"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_unstage("/unstage .", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("git_unstage", {"paths": ["."]})]
    assert lines == ["unstage failed: broad git path"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/unstage",
                "paths": ["."],
                "ok": False,
                "content": "broad git path",
            },
        )
    ]


def test_handle_diff_without_path_uses_empty_args() -> None:
    tools = FakeTools(ToolResult(tool="git_diff", ok=True, content="diff --git a/x"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_diff("/diff", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("git_diff", {})]
    assert lines == ["diff --git a/x"]
    assert transcript.events == [
        ("tool", {"command": "/diff", "path": "", "ok": True, "content": "diff --git a/x"})
    ]


def test_handle_diff_with_path_and_truncates_transcript_content() -> None:
    long_content = "x" * 2500
    tools = FakeTools(ToolResult(tool="git_diff", ok=True, content=long_content))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_diff("/diff src/a.py", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("git_diff", {"path": "src/a.py"})]
    # emit gets full content; transcript is truncated to 2000
    assert lines == [long_content]
    event = transcript.events[0][1]
    assert event["path"] == "src/a.py"
    assert event["ok"] is True
    assert len(event["content"]) == 2000
    assert event["content"] == long_content[:2000]


def test_handle_diff_failure_prefix() -> None:
    tools = FakeTools(ToolResult(tool="git_diff", ok=False, content="diff failed"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_diff("/diff", tools=tools, transcript=transcript, emit=emit)

    assert lines == ["工具執行失敗：diff failed"]


# --- /memory /fetch /run /test (low-risk tool-backed) ----------------------


def test_handle_memory_success_writes_slash_and_tool(tmp_path: Path) -> None:
    state = _state(tmp_path)
    tools = FakeTools(ToolResult(tool="memory_search", ok=True, content="hit: note"))
    transcript = FakeTranscript()
    lines, emit = _capture()
    usage: list[str] = []

    handle_memory(
        state,
        "/memory prior handoff",
        tools=tools,
        transcript=transcript,
        emit=emit,
        emit_usage=usage.append,
    )

    assert tools.calls == [
        ("memory_search", {"query": "prior handoff", "namespace": "project:test"})
    ]
    assert usage == []
    assert lines == ["hit: note"]
    assert transcript.events == [
        ("slash_command", {"command": "/memory prior handoff"}),
        (
            "tool",
            {
                "command": "/memory",
                "query": "prior handoff",
                "ok": True,
                "content": "hit: note",
            },
        ),
    ]


def test_handle_memory_empty_query_usage_no_tool(tmp_path: Path) -> None:
    state = _state(tmp_path)
    tools = FakeTools(ToolResult(tool="memory_search", ok=True, content="should not run"))
    transcript = FakeTranscript()
    lines, emit = _capture()
    usage: list[str] = []

    handle_memory(
        state,
        "/memory ",
        tools=tools,
        transcript=transcript,
        emit=emit,
        emit_usage=usage.append,
    )

    assert tools.calls == []
    assert lines == []
    assert usage == ["usage: /memory QUERY"]
    # slash_command is still written before the empty-query guard
    assert transcript.events == [("slash_command", {"command": "/memory "})]


def test_handle_memory_bare_command_usage_no_tool(tmp_path: Path) -> None:
    state = _state(tmp_path)
    tools = FakeTools(ToolResult(tool="memory_search", ok=True, content="should not run"))
    transcript = FakeTranscript()
    lines, emit = _capture()
    usage: list[str] = []

    handle_memory(
        state,
        "/memory",
        tools=tools,
        transcript=transcript,
        emit=emit,
        emit_usage=usage.append,
    )

    assert tools.calls == []
    assert lines == []
    assert usage == ["usage: /memory QUERY"]
    assert transcript.events == [("slash_command", {"command": "/memory"})]


def test_handle_memory_failure_prefix_and_truncation(tmp_path: Path) -> None:
    state = _state(tmp_path)
    long_content = "e" * 2500
    tools = FakeTools(ToolResult(tool="memory_search", ok=False, content=long_content))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_memory(
        state,
        "/memory boom",
        tools=tools,
        transcript=transcript,
        emit=emit,
    )

    assert lines == [f"memory search failed: {long_content}"]
    tool_event = transcript.events[1][1]
    assert tool_event["ok"] is False
    assert tool_event["query"] == "boom"
    assert len(tool_event["content"]) == 2000
    assert tool_event["content"] == long_content[:2000]


def test_handle_fetch_success_and_url_in_transcript() -> None:
    tools = FakeTools(ToolResult(tool="web_fetch", ok=True, content="<html>ok</html>"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_fetch(
        "/fetch https://example.com/page",
        tools=tools,
        transcript=transcript,
        emit=emit,
    )

    assert tools.calls == [("web_fetch", {"url": "https://example.com/page"})]
    assert lines == ["<html>ok</html>"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/fetch",
                "url": "https://example.com/page",
                "ok": True,
                "content": "<html>ok</html>",
            },
        )
    ]


def test_handle_fetch_failure_prefix_and_truncation_4000() -> None:
    long_content = "f" * 4500
    tools = FakeTools(ToolResult(tool="web_fetch", ok=False, content=long_content))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_fetch("/fetch http://bad", tools=tools, transcript=transcript, emit=emit)

    assert lines == [f"fetch failed: {long_content}"]
    event = transcript.events[0][1]
    assert event["ok"] is False
    assert event["url"] == "http://bad"
    assert len(event["content"]) == 4000
    assert event["content"] == long_content[:4000]


def test_handle_run_success_input_in_transcript() -> None:
    tools = FakeTools(ToolResult(tool="run_command", ok=True, content="ok\n"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_run("/run uv run pytest -q", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("run_command", {"command": "uv run pytest -q"})]
    assert lines == ["ok\n"]
    assert transcript.events == [
        (
            "tool",
            {
                "command": "/run",
                "input": "uv run pytest -q",
                "ok": True,
                "content": "ok\n",
            },
        )
    ]


def test_handle_run_failure_prefix_and_truncation_4000() -> None:
    long_content = "r" * 4500
    tools = FakeTools(ToolResult(tool="run_command", ok=False, content=long_content))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_run("/run echo hi", tools=tools, transcript=transcript, emit=emit)

    assert lines == [f"run failed: {long_content}"]
    event = transcript.events[0][1]
    assert event["input"] == "echo hi"
    assert event["ok"] is False
    assert len(event["content"]) == 4000


def test_handle_test_success() -> None:
    tools = FakeTools(ToolResult(tool="run_tests", ok=True, content="all passed"))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_test("/test", tools=tools, transcript=transcript, emit=emit)

    assert tools.calls == [("run_tests", {})]
    assert lines == ["all passed"]
    assert transcript.events == [
        ("tool", {"command": "/test", "ok": True, "content": "all passed"})
    ]


def test_handle_test_failure_prefix_and_truncation_4000() -> None:
    long_content = "t" * 4500
    tools = FakeTools(ToolResult(tool="run_tests", ok=False, content=long_content))
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_test("/test", tools=tools, transcript=transcript, emit=emit)

    assert lines == [f"驗證失敗：{long_content}"]
    event = transcript.events[0][1]
    assert event["ok"] is False
    assert len(event["content"]) == 4000
    assert event["content"] == long_content[:4000]


# --- /status /sessions /jobs /task readonly (inspection) -------------------


def test_handle_status_basic_fields_and_transcript(tmp_path: Path) -> None:
    state = _state(tmp_path, mode="agent", plan_mode=True)
    assert state.agent_session is not None
    state.agent_session.context_chars = 400  # ~100 tokens
    state.settings = state.settings.with_updates(model="test-model", persona="coder")
    transcript = FakeTranscript()
    lines, emit = _capture()
    panels: list[tuple[str, str]] = []

    handle_status(
        state,
        "/status",
        transcript=transcript,
        emit=emit,
        approval_mode="ask",
        message_count=3,
        format_status=format_plan_status,
        collect_aca_probe_info=None,
        emit_panel=lambda content, title: panels.append((content, title)),
    )

    assert transcript.events == [("slash_command", {"command": "/status"})]
    assert len(lines) == 1
    text = lines[0]
    assert "model=test-model" in text
    assert "mode=agent" in text
    assert f"plan={format_plan_status(True)}" in text
    assert "approval=ask (YELLOW 會詢問)" in text
    assert "namespace=project:test" in text
    assert "persona=coder" in text
    assert "context ~100 tokens" in text
    assert "messages=3" in text
    assert panels == []


def test_handle_status_without_session_zero_tokens(tmp_path: Path) -> None:
    state = _state(tmp_path, with_session=False)
    transcript = FakeTranscript()
    lines, emit = _capture()

    handle_status(
        state,
        "/status",
        transcript=transcript,
        emit=emit,
        approval_mode="auto",
        message_count=0,
        format_status=format_plan_status,
    )

    assert "context ~0 tokens" in lines[0]
    assert "approval=auto (YELLOW 自動執行)" in lines[0]
    assert "messages=0" in lines[0]


def test_handle_status_aca_probe_panel_when_available(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.settings = state.settings.with_updates(memory_backend="amh")
    state.memory = object()  # type: ignore[assignment]
    transcript = FakeTranscript()
    lines, emit = _capture()
    panels: list[tuple[str, str]] = []

    def fake_collect(_settings: Any, _memory: Any) -> dict[str, Any]:
        return {
            "client_type": "AmhClient",
            "latest_probe_expires": "2099-01-01",
            "latest_probe_audit": "2 events",
            "latest_probe_gov": "type=probe_completed, evidence_ids=['x']",
            "latest_probe_gov_audit_full": [
                "write: marker",
                "tier_upgrade\nconfirmed",
            ],
        }

    handle_status(
        state,
        "/status",
        transcript=transcript,
        emit=emit,
        approval_mode="off",
        message_count=1,
        format_status=format_plan_status,
        collect_aca_probe_info=fake_collect,
        emit_panel=lambda content, title: panels.append((content, title)),
    )

    assert any("記憶 client: AmhClient" in line for line in lines)
    assert any("最新 probe 過期: 2099-01-01" in line for line in lines)
    assert any("gov record: type=probe_completed" in line for line in lines)
    assert len(panels) == 1
    content, title = panels[0]
    assert title == "最新 probe gov audit events (ACA, 完整列表) — /status"
    assert "1. write: marker" in content
    assert "2. tier_upgrade | confirmed" in content
    assert "（已列出全部事件；長列表請向上捲動查看；完整列表亦見 /config 表格）" in content


def test_handle_status_aca_probe_swallowed_on_collector_error(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.settings = state.settings.with_updates(memory_backend="amh")
    state.memory = object()  # type: ignore[assignment]
    transcript = FakeTranscript()
    lines, emit = _capture()

    def boom(_settings: Any, _memory: Any) -> dict[str, Any]:
        raise RuntimeError("probe failed")

    handle_status(
        state,
        "/status",
        transcript=transcript,
        emit=emit,
        approval_mode="ask",
        message_count=0,
        format_status=format_plan_status,
        collect_aca_probe_info=boom,
        emit_panel=lambda *_a: None,
    )

    # Main status still emitted; probe failure is non-fatal
    assert len(lines) == 1
    assert "model=" in lines[0]


def test_handle_sessions_delegates_to_print_sessions(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    seen: list[Any] = []

    def fake_print_sessions(settings: Any) -> None:
        seen.append(settings)

    handle_sessions(
        state,
        "/sessions",
        transcript=transcript,
        print_sessions=fake_print_sessions,
    )

    assert transcript.events == [("slash_command", {"command": "/sessions"})]
    assert seen == [state.settings]


def test_handle_jobs_delegates_to_print_jobs(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    queue = object()
    seen: list[Any] = []

    def fake_print_jobs(job_queue: Any) -> None:
        seen.append(job_queue)

    handle_jobs(
        state,
        "/jobs",
        transcript=transcript,
        job_queue=queue,
        print_jobs=fake_print_jobs,
    )

    assert transcript.events == [("slash_command", {"command": "/jobs"})]
    assert seen == [queue]


def test_handle_task_readonly_status_list_empty() -> None:
    lines: list[str] = []
    panels: list[tuple[str, str]] = []
    tasks = [
        {"id": 1, "description": "do thing", "status": "in_progress", "notes": ""},
    ]

    def format_summary(ts: list[dict[str, Any]]) -> str:
        return f"summary:{len(ts)}"

    # empty value
    handled = handle_task_readonly(
        "",
        tasks=tasks,
        format_summary=format_summary,
        emit_panel=lambda c, t: panels.append((c, t)),
        emit=lines.append,
    )
    assert handled is True
    assert panels == [("summary:1", "Task List (多任務清單)")]
    assert lines == ["[dim]提示：使用 /task update <id> done|in_progress [notes] 來更新[/dim]"]

    # status
    panels.clear()
    lines.clear()
    assert handle_task_readonly(
        "status",
        tasks=[],
        format_summary=format_summary,
        emit_panel=lambda c, t: panels.append((c, t)),
        emit=lines.append,
    )
    assert panels == [("summary:0", "Task List (多任務清單)")]
    assert lines == []  # no hint when empty task list

    # list
    assert handle_task_readonly(
        "list",
        tasks=[],
        format_summary=format_summary,
        emit_panel=lambda c, t: panels.append((c, t)),
        emit=lines.append,
    )


def test_handle_task_readonly_does_not_claim_write_branches() -> None:
    calls: list[str] = []

    for value in ("add foo", "update 1 done", "done 1", "clear", "free text task"):
        handled = handle_task_readonly(
            value,
            tasks=[],
            format_summary=lambda _t: "x",
            emit_panel=lambda c, t: calls.append(f"panel:{c}:{t}"),
            emit=lambda m: calls.append(f"emit:{m}"),
        )
        assert handled is False

    assert calls == []


# --- /help /guide /workflows /tools /context /history /transcript ---------


def test_handle_help_writes_transcript_and_calls_print(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    calls: list[str] = []

    handle_help(
        state,
        "/help",
        transcript=transcript,
        print_slash_help=lambda: calls.append("help"),
    )

    assert transcript.events == [("slash_command", {"command": "/help"})]
    assert calls == ["help"]


def test_handle_guide_marks_seen_then_prints(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    order: list[str] = []
    seen_workspaces: list[Any] = []

    def mark_seen(workspace: Any) -> None:
        order.append("mark_seen")
        seen_workspaces.append(workspace)

    def print_guide() -> None:
        order.append("print_guide")

    handle_guide(
        state,
        "/guide",
        transcript=transcript,
        print_guide=print_guide,
        mark_guide_hint_seen=mark_seen,
    )

    assert transcript.events == [("slash_command", {"command": "/guide"})]
    assert seen_workspaces == [state.settings.workspace]
    # Historical order: transcript write → mark_seen(workspace) → print_guide
    assert order == ["mark_seen", "print_guide"]


def test_handle_workflows_writes_transcript_and_calls_print(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    calls: list[str] = []

    handle_workflows(
        state,
        "/workflows",
        transcript=transcript,
        print_workflows=lambda: calls.append("workflows"),
    )

    assert transcript.events == [("slash_command", {"command": "/workflows"})]
    assert calls == ["workflows"]


def test_handle_tools_passes_tools_registry(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    tools = object()
    seen: list[Any] = []

    handle_tools(
        state,
        "/tools",
        transcript=transcript,
        tools=tools,
        print_tools=lambda t: seen.append(t),
    )

    assert transcript.events == [("slash_command", {"command": "/tools"})]
    assert seen == [tools]


def test_handle_context_passes_session_and_messages(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    session = FakeAgentSession(context_chars=100)
    messages = [{"role": "user", "content": "hi"}]
    seen: list[tuple[Any, Any]] = []

    handle_context(
        state,
        "/context",
        transcript=transcript,
        agent_session=session,
        chat_messages=messages,
        print_context=lambda sess, msgs: seen.append((sess, msgs)),
    )

    assert transcript.events == [("slash_command", {"command": "/context"})]
    assert seen == [(session, messages)]


def test_handle_history_passes_history(tmp_path: Path) -> None:
    state = _state(tmp_path)
    transcript = FakeTranscript()
    history = [("chat", "hello"), ("agent", "do stuff")]
    seen: list[Any] = []

    handle_history(
        state,
        "/history",
        transcript=transcript,
        history=history,
        print_history=lambda h: seen.append(h),
    )

    assert transcript.events == [("slash_command", {"command": "/history"})]
    assert seen == [history]


def test_handle_transcript_emits_path(tmp_path: Path) -> None:
    state = _state(tmp_path)
    path = tmp_path / "session.jsonl"
    transcript = FakeTranscript(path=path)
    lines, emit = _capture()

    handle_transcript(
        state,
        "/transcript",
        transcript=transcript,
        emit=emit,
    )

    assert transcript.events == [("slash_command", {"command": "/transcript"})]
    assert lines == [str(path)]
