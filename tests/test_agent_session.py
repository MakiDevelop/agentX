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
    assert answer == "final attempt"


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
    assert answer == "works"


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
