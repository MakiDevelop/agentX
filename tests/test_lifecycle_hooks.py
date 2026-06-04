from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agentx.config import Settings
from agentx.hooks import (
    CompactContext,
    ErrorHookContext,
    FinalAnswerContext,
    HookEvent,
    HookManager,
    SessionEndContext,
    SessionStartContext,
    TurnEndContext,
    TurnStartContext,
)
from agentx.loop import AgentSession
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
        learning_enabled=False,
    )


def _session(
    tmp_path: Path,
    responses: Sequence[str],
    max_steps: int = 5,
    hooks: HookManager | None = None,
) -> tuple[AgentSession, FakeOllama]:
    ollama = FakeOllama(responses)
    memory = FakeMemory()
    registry = ToolRegistry(builtin_tools(tmp_path, memory))  # type: ignore[arg-type]
    settings = _make_settings(tmp_path, max_steps=max_steps)
    session = AgentSession(
        settings=settings,
        ollama=ollama,
        tools=registry,
        memory=memory,  # type: ignore[arg-type]
        hooks=hooks,
    )
    return session, ollama


def test_new_hook_events_exist() -> None:
    assert HookEvent.SESSION_START.value == "SessionStart"
    assert HookEvent.SESSION_END.value == "SessionEnd"
    assert HookEvent.FINAL_ANSWER.value == "FinalAnswer"
    assert HookEvent.TURN_START.value == "TurnStart"
    assert HookEvent.TURN_END.value == "TurnEnd"
    assert HookEvent.COMPACT.value == "Compact"
    assert HookEvent.ERROR.value == "Error"


def test_session_start_and_final_answer_hooks_fire(tmp_path: Path) -> None:
    events: list[str] = []
    hooks = HookManager()
    hooks.add(HookEvent.SESSION_START, lambda ctx: events.append("start"))
    hooks.add(HookEvent.FINAL_ANSWER, lambda ctx: events.append("final"))

    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'], hooks=hooks)
    session.ask("hi")

    assert "start" in events
    assert "final" in events


def test_final_answer_context_has_content(tmp_path: Path) -> None:
    captured: list[FinalAnswerContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.FINAL_ANSWER, lambda ctx: captured.append(ctx))

    session, _ = _session(tmp_path, ['{"type":"final","content":"the answer"}'], hooks=hooks)
    session.ask("question")

    assert len(captured) == 1
    assert captured[0].content == "the answer"
    assert captured[0].plan_only is False


def test_turn_start_and_end_fire_on_tool_call(tmp_path: Path) -> None:
    starts: list[TurnStartContext] = []
    ends: list[TurnEndContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.TURN_START, lambda ctx: starts.append(ctx))
    hooks.add(HookEvent.TURN_END, lambda ctx: ends.append(ctx))

    session, _ = _session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"memory_search","args":{"query":"x"}}',
            '{"type":"final","content":"done"}',
        ],
        hooks=hooks,
    )
    session.ask("test")

    assert len(starts) >= 2
    assert starts[0].step == 0
    assert len(ends) >= 1
    assert ends[0].action_type == "tool_call"
    assert ends[0].tool_name == "memory_search"


def test_session_end_fires_on_max_steps(tmp_path: Path) -> None:
    captured: list[SessionEndContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.SESSION_END, lambda ctx: captured.append(ctx))

    session, _ = _session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"memory_search","args":{"query":"x"}}',
            '{"type":"tool_call","tool":"memory_search","args":{"query":"y"}}',
            '{"type":"tool_call","tool":"memory_search","args":{"query":"z"}}',
            '{"type":"tool_call","tool":"memory_search","args":{"query":"w"}}',
            '{"type":"tool_call","tool":"memory_search","args":{"query":"v"}}',
            '{"type":"final","content":"fallback"}',
        ],
        max_steps=2,
        hooks=hooks,
    )
    session.ask("go")

    assert len(captured) == 1
    assert captured[0].termination == "max_steps_exceeded"


def test_error_hook_fires_on_tool_failure(tmp_path: Path) -> None:
    captured: list[ErrorHookContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.ERROR, lambda ctx: captured.append(ctx))

    session, _ = _session(
        tmp_path,
        [
            '{"type":"tool_call","tool":"read_file","args":{"path":"nonexistent_file_xyz.txt"}}',
            '{"type":"final","content":"done"}',
        ],
        hooks=hooks,
    )
    session.ask("read a missing file")

    assert len(captured) >= 1
    assert captured[0].tool_name == "read_file"


def test_compact_hook_fires(tmp_path: Path) -> None:
    captured: list[CompactContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.COMPACT, lambda ctx: captured.append(ctx))

    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'], hooks=hooks)
    for i in range(10):
        session.messages.append({"role": "user", "content": f"padding message {i}" * 50})
    session.compact()

    assert len(captured) == 1
    assert captured[0].before_count > captured[0].after_count


def test_hooks_not_required(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, ['{"type":"final","content":"done"}'])
    result = session.ask("hi")
    assert result == "done"
