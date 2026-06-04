from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentx.protocol import ToolResult
from agentx.safety import Risk


class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    FINAL_ANSWER = "FinalAnswer"
    TURN_START = "TurnStart"
    TURN_END = "TurnEnd"
    COMPACT = "Compact"
    ERROR = "Error"


class HookVeto(Exception):
    """Backward-compatible block signal.

    New code should return ``HookResult(decision='block', reason=...)``.
    Raising ``HookVeto`` is still supported and gets mapped to the same
    structured result.
    """


@dataclass
class HookResult:
    decision: str = "allow"
    reason: str | None = None
    updated_args: dict[str, Any] | None = None
    additional_context: str | None = None
    system_message: str | None = None

    @property
    def blocked(self) -> bool:
        return self.decision == "block"


@dataclass
class ToolCallContext:
    tool: str
    args: dict[str, Any]
    risk: Risk


@dataclass
class ToolResultContext:
    tool: str
    args: dict[str, Any]
    result: ToolResult


@dataclass
class SessionStartContext:
    namespace: str
    prompt: str


@dataclass
class SessionEndContext:
    namespace: str
    termination: str
    message_count: int
    error_count: int


@dataclass
class FinalAnswerContext:
    content: str
    plan_only: bool
    message_count: int


@dataclass
class TurnStartContext:
    step: int
    message_count: int
    tokens_estimate: int


@dataclass
class TurnEndContext:
    step: int
    action_type: str
    tool_name: str | None = None
    result_ok: bool | None = None


@dataclass
class CompactContext:
    before_count: int
    after_count: int
    tokens_estimate: int
    summary: str


@dataclass
class ErrorHookContext:
    tool_name: str
    error_type: str
    error_message: str
    is_stuck: bool
    error_history_length: int


HookCallback = Callable[[Any], "HookResult | None"]


class HookManager:
    def __init__(self) -> None:
        self._listeners: dict[str, list[HookCallback]] = defaultdict(list)

    def add(self, event: HookEvent | str, callback: HookCallback) -> None:
        self._listeners[_key(event)].append(callback)

    def remove(self, event: HookEvent | str, callback: HookCallback) -> None:
        listeners = self._listeners.get(_key(event), [])
        if callback in listeners:
            listeners.remove(callback)

    def listeners(self, event: HookEvent | str) -> list[HookCallback]:
        return list(self._listeners.get(_key(event), []))

    def fire(self, event: HookEvent | str, context: Any) -> HookResult:
        merged = HookResult()
        for callback in list(self._listeners.get(_key(event), [])):
            try:
                result = callback(context)
            except HookVeto as veto:
                return HookResult(decision="block", reason=str(veto))
            if result is None:
                continue
            merged = _merge_results(merged, result)
            if merged.blocked:
                return merged
        return merged


def _key(event: HookEvent | str) -> str:
    return event.value if isinstance(event, HookEvent) else event


def _merge_results(a: HookResult, b: HookResult) -> HookResult:
    return HookResult(
        decision="block" if b.decision == "block" else a.decision,
        reason=b.reason or a.reason,
        updated_args=b.updated_args if b.updated_args is not None else a.updated_args,
        additional_context=_concat(a.additional_context, b.additional_context),
        system_message=_concat(a.system_message, b.system_message),
    )


def _concat(a: str | None, b: str | None) -> str | None:
    if a and b:
        return f"{a}\n{b}"
    return b or a
