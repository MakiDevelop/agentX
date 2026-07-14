"""Coverage for runtime slash handlers used by run_shell() nested handlers.

These tests exercise ``agentx.cli_runtime_handlers`` — the real interactive
logic for /plan, /execute, /mode — not the simplified ``cli_slash_shims``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentx.cli import ShellState, format_plan_status
from agentx.cli_runtime_handlers import (
    EXECUTE_SYSTEM_MESSAGE,
    handle_execute,
    handle_mode,
    handle_plan,
)
from helpers import make_settings


@dataclass
class FakeTranscript:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def write(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


@dataclass
class FakeAgentSession:
    plan_only: bool = False
    messages: list[dict[str, str]] = field(default_factory=list)


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
