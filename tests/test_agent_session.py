import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agentx.config import Settings
from agentx.hooks import HookEvent, HookManager, ToolCallContext
from agentx.loop import AgentSession
from agentx.protocol import Risk
from agentx.tools import ToolRegistry, builtin_tools


class FakeOllama:
    model = "fake"

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, str]], bool]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        self.calls.append((list(messages), json_mode))
        return self.responses.pop(0)


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"


def _make_settings(workspace: Path, max_steps: int = 5) -> Settings:
    return Settings.from_values(
        model="fake",
        ollama_url="http://localhost:11434",
        ollama_timeout=60,
        memory_hall_url="http://localhost:9100",
        memory_hall_token=None,
        max_steps=max_steps,
        context_limit_tokens=8192,
        auto_handoff=False,
        persona="default",
        workspace=workspace,
    )


def _session(tmp_path: Path, responses: Sequence[str], max_steps: int = 5) -> tuple[AgentSession, FakeOllama]:
    ollama = FakeOllama(responses)
    memory = FakeMemory()
    registry = ToolRegistry(builtin_tools(tmp_path, memory))  # type: ignore[arg-type]
    settings = _make_settings(tmp_path, max_steps=max_steps)
    session = AgentSession(
        settings=settings,
        ollama=ollama,
        tools=registry,
        memory=memory,  # type: ignore[arg-type]
    )
    return session, ollama


def test_final_answer_terminates(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    assert session.ask("hi") == "done"


def test_tool_call_then_final(tmp_path: Path) -> None:
    session, _ = _session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"memory_search","args":{"query":"x"}}',
            '{"type":"final","content":"after tool"}',
        ],
    )
    assert session.ask("use a tool") == "after tool"


def test_session_hooks_are_connected_to_tool_registry(tmp_path: Path) -> None:
    seen: list[str] = []
    hooks = HookManager()

    def observe(ctx: ToolCallContext) -> None:
        seen.append(ctx.tool)

    hooks.add(HookEvent.PRE_TOOL_USE, observe)
    ollama = FakeOllama(
        [
            '{"type":"tool_call","tool":"memory_search","args":{"query":"x"}}',
            '{"type":"final","content":"done"}',
        ]
    )
    memory = FakeMemory()
    registry = ToolRegistry(builtin_tools(tmp_path, memory))  # type: ignore[arg-type]
    session = AgentSession(
        settings=_make_settings(tmp_path),
        ollama=ollama,  # type: ignore[arg-type]
        tools=registry,
        memory=memory,  # type: ignore[arg-type]
        hooks=hooks,
    )

    assert session.ask("use a tool") == "done"
    assert seen == ["memory_search"]


def test_invalid_json_retries_then_final(tmp_path: Path) -> None:
    session, _ = _session(
        tmp_path,
        [
            "plain text not json",
            '{"type":"final","content":"recovered"}',
        ],
    )
    assert session.ask("anything") == "recovered"


def test_bad_schema_retries_then_final(tmp_path: Path) -> None:
    session, _ = _session(
        tmp_path,
        [
            '{"type":"tool_call","missing":"fields"}',
            '{"type":"final","content":"fixed"}',
        ],
    )
    assert session.ask("retry") == "fixed"


def test_max_steps_returns_stop_message(tmp_path: Path) -> None:
    session, _ = _session(
        tmp_path,
        ["not json", "still not json"],
        max_steps=2,
    )
    assert "停止" in session.ask("hi")


def test_compact_preserves_recent_tail(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.ask("hi")
    before = session.message_count
    note = session.compact(keep_last=2)
    assert session.compaction_count == 1
    assert "壓縮" in note
    assert session.message_count <= before


def test_ask_reports_final_termination_on_clean_finish(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    assert session.last_termination == "unknown"
    session.ask("hi")
    assert session.last_termination == "final"
    assert session.last_failing_tools == set()


def test_ask_reports_max_steps_termination(tmp_path: Path) -> None:
    session, _ = _session(
        tmp_path,
        ["bogus", "bogus", "bogus"],
        max_steps=2,
    )
    answer = session.ask("hi")
    assert "停止" in answer
    assert session.last_termination == "max_steps_exceeded"


class _StubTool:
    risk = Risk.GREEN

    def __init__(self, name: str, returns: str = "", raises: Exception | None = None) -> None:
        self.name = name
        self.description = name
        self._returns = returns
        self._raises = raises

    def run(self, args: dict[str, Any]) -> str:
        if self._raises is not None:
            raise self._raises
        return self._returns


class _FlakyTool:
    name = "flaky"
    description = "fails first, succeeds after"
    risk = Risk.GREEN

    def __init__(self) -> None:
        self.calls = 0

    def run(self, args: dict[str, Any]) -> str:
        self.calls += 1
        code = 1 if self.calls == 1 else 0
        return f"$ flaky\nexit={code}\n"


def _guard_session(
    tmp_path: Path,
    responses: Sequence[str],
    tools: list[object],
    max_steps: int = 10,
) -> AgentSession:
    ollama = FakeOllama(responses)
    memory = FakeMemory()
    registry = ToolRegistry(tools)  # type: ignore[arg-type]
    settings = _make_settings(tmp_path, max_steps=max_steps)
    return AgentSession(
        settings=settings,
        ollama=ollama,
        tools=registry,
        memory=memory,  # type: ignore[arg-type]
    )


def test_final_blocked_when_tool_content_has_nonzero_exit(tmp_path: Path) -> None:
    session = _guard_session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"fail_cmd","args":{}}',
            '{"type":"final","content":"completed successfully"}',
            '{"type":"final","content":"卡住了"}',
            '{"type":"final","content":"放棄"}',
            '{"type":"final","content":"final attempt"}',
        ],
        [_StubTool("fail_cmd", returns="$ thing\nexit=1\nerror: nope")],
    )
    answer = session.ask("hi")
    # After N7 fix: retries-exhausted with unresolved failure → forced failure
    # summary instead of the model's "final attempt" claim.
    assert answer.startswith("任務失敗")
    assert "fail_cmd" in answer
    assert "final attempt" in answer  # original model claim preserved as reference
    assert session.last_termination == "final"
    assert session.last_failing_tools == {"fail_cmd"}


def test_final_blocked_when_tool_raised(tmp_path: Path) -> None:
    session = _guard_session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"boom","args":{}}',
            '{"type":"final","content":"works"}',
            '{"type":"final","content":"works"}',
            '{"type":"final","content":"works"}',
            '{"type":"final","content":"works"}',
        ],
        [_StubTool("boom", raises=RuntimeError("kaboom"))],
    )
    answer = session.ask("hi")
    assert answer.startswith("任務失敗")
    assert "boom" in answer
    assert session.last_failing_tools == {"boom"}


def test_final_accepted_after_same_tool_succeeds(tmp_path: Path) -> None:
    session = _guard_session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"flaky","args":{}}',
            '{"type":"tool_call","tool":"flaky","args":{}}',
            '{"type":"final","content":"recovered"}',
        ],
        [_FlakyTool()],
    )
    assert session.ask("hi") == "recovered"


def test_final_accepted_when_no_recent_failure(tmp_path: Path) -> None:
    session = _guard_session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"ok_cmd","args":{}}',
            '{"type":"final","content":"all good"}',
        ],
        [_StubTool("ok_cmd", returns="$ x\nexit=0\n")],
    )
    assert session.ask("hi") == "all good"


def test_auto_compact_triggers_above_threshold(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=200)
    session.messages.append({"role": "user", "content": "x" * 2000})
    assert session.compaction_count == 0
    session.ask("hi")
    assert session.compaction_count >= 1


def test_auto_compact_skips_below_threshold(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=100_000)
    assert session.compaction_count == 0
    session.ask("hi")
    assert session.compaction_count == 0


def test_auto_compact_disabled_when_limit_zero(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=0)
    session.messages.append({"role": "user", "content": "x" * 5000})
    session.ask("hi")
    assert session.compaction_count == 0


def test_auto_compact_skipped_when_no_growth_since_last(tmp_path: Path) -> None:
    """Repeated _maybe_auto_compact() calls without intervening message growth
    should compact only once — bootstrap-on-its-own-over-threshold should not
    re-compact every turn (hysteresis, review N8)."""
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=200)
    session.messages.append({"role": "user", "content": "x" * 2000})

    session._maybe_auto_compact()
    assert session.compaction_count == 1

    # No new messages added → growth = 0 → hysteresis kicks in.
    session._maybe_auto_compact()
    assert session.compaction_count == 1
    session._maybe_auto_compact()
    assert session.compaction_count == 1


def test_clear_resets_compact_hysteresis(tmp_path: Path) -> None:
    """clear() must drop _last_compact_tokens so a fresh task in the same
    AgentSession can re-trigger auto-compact (review codex C2)."""
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=200)
    session.messages.append({"role": "user", "content": "x" * 2000})
    session._maybe_auto_compact()
    assert session.compaction_count == 1
    assert session._last_compact_tokens is not None

    session.clear()
    assert session._last_compact_tokens is None
    assert session._tool_outcomes == {}
    assert session.last_termination == "unknown"
    assert session.last_failing_tools == set()


def test_failing_tool_remembered_across_many_later_calls(tmp_path: Path) -> None:
    """A nonzero-exit tool result must keep flagging the tool as unresolved
    even after 12+ other tool calls happen later (review codex C3:
    sliding window was too narrow)."""
    session, _ = _session(tmp_path, [])
    session._tool_outcomes = {}
    # Simulate one failed tool followed by 20 other-tool successes.
    from agentx.protocol import ToolResult

    class _FakeTools:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, name: str, args: dict, **kwargs: Any) -> ToolResult:
            # Accept _return_effective (and any future internal kwargs) for compatibility
            # with the real ToolRegistry after Codex feedback fixes.
            self.calls += 1
            if name == "fail_cmd":
                return ToolResult(tool="fail_cmd", ok=True, content="$ x\nexit=1\nerror")
            return ToolResult(tool=name, ok=True, content="ok")

    session.tools = _FakeTools()  # type: ignore[assignment]
    from agentx.protocol import ToolCall

    session._run_tool(ToolCall(type="tool_call", tool="fail_cmd", args={}))
    assert "fail_cmd" in session._unresolved_failing_tools()

    for i in range(20):
        session._run_tool(ToolCall(type="tool_call", tool=f"other_{i}", args={}))

    # Failed tool still tracked despite many later successful tool calls.
    assert "fail_cmd" in session._unresolved_failing_tools()


def test_auto_compact_failure_does_not_break_loop(tmp_path: Path, monkeypatch) -> None:
    """If compact() raises, the agent loop continues without crashing
    (review N8)."""
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.settings = session.settings.with_updates(context_limit_tokens=200)
    session.messages.append({"role": "user", "content": "x" * 2000})

    def explode(*_args, **_kwargs):
        raise RuntimeError("compact go boom")

    monkeypatch.setattr(session, "compact", explode)
    # Should not raise — exception swallowed.
    answer = session.ask("hi")
    assert answer == "done"
    assert session.last_termination == "final"


def _record_tool_call(tool: str, args: dict) -> dict:
    import json as _json

    return {
        "role": "assistant",
        "content": _json.dumps({"type": "tool_call", "tool": tool, "args": args}),
    }


def test_compact_includes_modified_files_tag(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.messages.append(_record_tool_call("write_file", {"path": "src/a.rs", "content": "x"}))
    session.messages.append(_record_tool_call("edit_file", {"path": "src/b.rs", "edits": []}))
    note = session.compact()

    summary = session.messages[-1]["content"]
    assert "<modified-files>" in summary
    assert "src/a.rs" in summary
    assert "src/b.rs" in summary
    assert "壓縮" in note


def test_compact_includes_read_files_tag(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.messages.append(_record_tool_call("read_file", {"path": "src/c.rs"}))
    session.compact()

    summary = session.messages[-1]["content"]
    assert "<read-files>" in summary
    assert "src/c.rs" in summary


def test_compact_read_then_write_only_listed_as_modified(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    session.messages.append(_record_tool_call("read_file", {"path": "shared.rs"}))
    session.messages.append(_record_tool_call("write_file", {"path": "shared.rs", "content": "x"}))
    session.compact()

    summary = session.messages[-1]["content"]
    assert "<modified-files>" in summary
    assert "shared.rs" in summary
    # 不該同時出現在 read-files
    read_block_start = summary.find("<read-files>")
    if read_block_start != -1:
        read_block = summary[read_block_start:summary.find("</read-files>")]
        assert "shared.rs" not in read_block
