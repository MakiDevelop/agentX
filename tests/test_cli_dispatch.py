import threading
from pathlib import Path
from typing import Any

from agentx.approval import ApprovalMode, ApprovalPolicy
from agentx.cli import (
    NON_BLOCKING_COMMANDS,
    SLASH_HANDLERS,
    ShellState,
    cmd_clear,
    cmd_exit,
    cmd_files,
    cmd_mode,
    cmd_plan,
    cmd_quit,
    dispatch_slash,
)
from agentx.config import Settings
from agentx.jobs import PromptJobQueue
from agentx.protocol import ToolResult
from agentx.task import TaskState


class FakeOllama:
    model = "fake"

    def chat(self, messages: Any, **kwargs: Any) -> str:  # pragma: no cover - not invoked
        return ""


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, tool: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((tool, args))
        return ToolResult(tool=tool, ok=True, content=f"ran {tool} {args}")

    def describe_tools(self) -> dict[str, str]:
        return {}


class FakeAgentSession:
    def __init__(self) -> None:
        self.cleared = 0
        self.messages: list[dict[str, str]] = []

    def clear(self) -> None:
        self.cleared += 1


class FakeTranscript:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.path = Path("/tmp/fake.jsonl")

    def write(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


def _settings(tmp_path: Path) -> Settings:
    return Settings.from_values(
        model="fake",
        ollama_url="http://localhost:11434",
        ollama_timeout=60,
        memory_hall_url="http://localhost:9100",
        memory_hall_token=None,
        max_steps=8,
        context_limit_tokens=8192,
        auto_handoff=False,
        persona="default",
        workspace=tmp_path,
    )


def _state(tmp_path: Path) -> ShellState:
    return ShellState(
        settings=_settings(tmp_path),
        ollama=FakeOllama(),  # type: ignore[arg-type]
        memory=FakeMemory(),  # type: ignore[arg-type]
        tools=FakeTools(),  # type: ignore[arg-type]
        agent_session=FakeAgentSession(),  # type: ignore[arg-type]
        transcript=FakeTranscript(),  # type: ignore[arg-type]
        job_queue=PromptJobQueue(),
        approval_policy=ApprovalPolicy(mode=ApprovalMode.ASK),
        task=TaskState(title=None, status="idle", created_at=None, updated_at=None),
        namespace="project:test",
        mode="chat",
    )


def test_dispatch_unknown_returns_false(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert dispatch_slash(state, "/totally-fake") is False


def test_dispatch_known_returns_true(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert dispatch_slash(state, "/plan") is True


def test_dispatch_splits_command_and_arg(tmp_path: Path) -> None:
    state = _state(tmp_path)
    dispatch_slash(state, "/files src/")
    tools: FakeTools = state.tools  # type: ignore[assignment]
    assert tools.calls == [("list_files", {"path": "src/"})]


def test_cmd_plan_toggles(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.plan_mode is False
    cmd_plan(state, "")
    assert state.plan_mode is True
    cmd_plan(state, "")
    assert state.plan_mode is False


def test_cmd_mode_switches_and_rejects(tmp_path: Path) -> None:
    state = _state(tmp_path)
    cmd_mode(state, "agent")
    assert state.mode == "agent"
    cmd_mode(state, "bogus")
    assert state.mode == "agent"


def test_cmd_exit_sets_should_exit(tmp_path: Path) -> None:
    state = _state(tmp_path)
    cmd_exit(state, "")
    assert state.should_exit is True
    assert state.exit_reason == "/exit"


def test_cmd_quit_sets_should_exit(tmp_path: Path) -> None:
    state = _state(tmp_path)
    cmd_quit(state, "")
    assert state.should_exit is True
    assert state.exit_reason == "/quit"


def test_cmd_files_defaults_to_dot(tmp_path: Path) -> None:
    state = _state(tmp_path)
    cmd_files(state, "")
    tools: FakeTools = state.tools  # type: ignore[assignment]
    assert tools.calls == [("list_files", {"path": "."})]


def test_cmd_clear_resets_session(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.chat_messages.append({"role": "user", "content": "x"})
    cmd_clear(state, "")
    session: FakeAgentSession = state.agent_session  # type: ignore[assignment]
    assert session.cleared == 1
    assert len(state.chat_messages) == 1
    assert state.chat_messages[0]["role"] == "system"


def test_non_blocking_commands_set() -> None:
    assert NON_BLOCKING_COMMANDS == {"/jobs", "/cancel"}


def test_all_slash_commands_have_handlers() -> None:
    declared = {
        entry[0].split()[0]
        for entry in __import__("agentx.cli", fromlist=["SLASH_COMMANDS"]).SLASH_COMMANDS
    }
    declared.discard("/exit")
    declared.discard("/quit")
    missing = declared - set(SLASH_HANDLERS.keys())
    assert not missing, f"slash commands without handlers: {missing}"


def test_current_cancel_is_event(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert isinstance(state.current_cancel, threading.Event)
    assert isinstance(state.prompt_active, threading.Event)
