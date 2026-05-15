import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from agentx.config import Settings
from agentx.loop import AgentSession
from agentx.tools import ToolRegistry


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
    registry = ToolRegistry(workspace=tmp_path, memory=FakeMemory())  # type: ignore[arg-type]
    settings = _make_settings(tmp_path, max_steps=max_steps)
    session = AgentSession(settings=settings, ollama=ollama, tools=registry)  # type: ignore[arg-type]
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
