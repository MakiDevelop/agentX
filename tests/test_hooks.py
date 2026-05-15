import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agentx.config import Settings
from agentx.hooks import (
    ChatContext,
    CompactContext,
    HookEvent,
    HookManager,
    HookVeto,
    ToolCallContext,
    ToolResultContext,
)
from agentx.loop import AgentSession
from agentx.protocol import Risk
from agentx.tools import ToolRegistry


class EchoTool:
    name = "echo"
    description = "echo"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return f"echo:{args.get('value', '')}"


class FakeOllama:
    model = "fake"

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        return self.responses.pop(0)


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"


def _settings(workspace: Path, max_steps: int = 5) -> Settings:
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


def test_before_and_after_tool_call_observe() -> None:
    seen: list[tuple[str, Any]] = []
    hooks = HookManager()
    hooks.add(HookEvent.BEFORE_TOOL_CALL, lambda ctx: seen.append(("before", ctx)))
    hooks.add(HookEvent.AFTER_TOOL_CALL, lambda ctx: seen.append(("after", ctx)))

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {"value": "hi"})

    assert result.ok
    assert [event for event, _ in seen] == ["before", "after"]
    before_ctx = seen[0][1]
    after_ctx = seen[1][1]
    assert isinstance(before_ctx, ToolCallContext)
    assert before_ctx.tool == "echo"
    assert before_ctx.risk == Risk.GREEN
    assert isinstance(after_ctx, ToolResultContext)
    assert after_ctx.result.ok
    assert after_ctx.result.content == "echo:hi"


def test_before_tool_call_veto_blocks_run() -> None:
    after_calls: list[ToolResultContext] = []
    hooks = HookManager()

    def veto(ctx: ToolCallContext) -> None:
        raise HookVeto(f"blocked {ctx.tool}")

    hooks.add(HookEvent.BEFORE_TOOL_CALL, veto)
    hooks.add(HookEvent.AFTER_TOOL_CALL, after_calls.append)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {})

    assert not result.ok
    assert "Vetoed by hook" in result.content
    assert after_calls == []


def test_on_compact_fires_from_session(tmp_path: Path) -> None:
    contexts: list[CompactContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.ON_COMPACT, contexts.append)

    session = AgentSession(
        settings=_settings(tmp_path),
        ollama=FakeOllama([]),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        hooks=hooks,
    )
    note = session.compact(keep_last=2)

    assert "壓縮" in note
    assert len(contexts) == 1
    assert contexts[0].keep_last == 2


def test_on_compact_veto_aborts(tmp_path: Path) -> None:
    hooks = HookManager()

    def veto(ctx: CompactContext) -> None:
        raise HookVeto("no compact")

    hooks.add(HookEvent.ON_COMPACT, veto)

    session = AgentSession(
        settings=_settings(tmp_path),
        ollama=FakeOllama([]),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        hooks=hooks,
    )
    before = session.message_count
    note = session.compact()

    assert "中止" in note
    assert session.message_count == before
    assert session.compaction_count == 0


def test_before_chat_fires_per_iteration(tmp_path: Path) -> None:
    contexts: list[ChatContext] = []
    hooks = HookManager()
    hooks.add(HookEvent.BEFORE_CHAT, contexts.append)

    session = AgentSession(
        settings=_settings(tmp_path),
        ollama=FakeOllama(['{"type":"final","content":"done"}']),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        hooks=hooks,
    )
    answer = session.ask("hi")

    assert answer == "done"
    assert len(contexts) == 1
    assert contexts[0].json_mode is True


def test_before_chat_veto_returns_stop_message(tmp_path: Path) -> None:
    hooks = HookManager()

    def veto(ctx: ChatContext) -> None:
        raise HookVeto("not allowed")

    hooks.add(HookEvent.BEFORE_CHAT, veto)

    session = AgentSession(
        settings=_settings(tmp_path),
        ollama=FakeOllama([]),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        hooks=hooks,
    )
    assert "中止" in session.ask("hi")


def test_remove_hook_stops_firing() -> None:
    calls: list[str] = []

    def callback(ctx: ToolCallContext) -> None:
        calls.append(ctx.tool)

    hooks = HookManager()
    hooks.add(HookEvent.BEFORE_TOOL_CALL, callback)
    hooks.remove(HookEvent.BEFORE_TOOL_CALL, callback)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    registry.run("echo", {})

    assert calls == []
