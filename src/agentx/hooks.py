"""Lifecycle Hooks for agentX (richer than pi's 2-hook model).

This module implements the hook system described in AGENTX.md and the
lifecycle events used by AgentSession / ToolRegistry / Loop.

Design notes (borrowed from earendil-works/pi hook contracts, adapted):

- Callbacks MUST NOT raise exceptions (except the backward-compat HookVeto).
  Uncaught errors are swallowed to keep the agent loop alive.
- PRE_TOOL_USE can veto (block execution) or rewrite args.
- POST_TOOL_USE can inject additional_context into the tool result, or veto.
- Multiple listeners for the same event have their HookResult merged:
    * block decision is OR-ed (any block wins)
    * updated_args: last non-None wins
    * additional_context / system_message: concatenated with newlines
- PRE_TOOL_USE listeners are currently invoked sequentially (registration order).
  When parallel tool execution is enabled in the future, multiple beforeToolCall
  style listeners may be allowed to run concurrently (pi contract language).
- Long-running hook work should be fire-and-forget (e.g. via background task);
  the core contract expects hooks to be fast.

See also:
- tools/registry.py for PRE/POST_TOOL_USE usage
- loop.py for SESSION_*, TURN_*, FINAL_ANSWER, COMPACT, ERROR
- tests/test_hooks.py and tests/test_lifecycle_hooks.py
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentx.protocol import ToolResult
from agentx.safety import Risk


class HookEvent(str, Enum):
    """Agent lifecycle events.

    Hook callbacks for all events:
    - MUST NOT raise exceptions (uncaught errors are swallowed; only HookVeto
      is turned into a structured block result).
    - MUST complete quickly (long operations should be fire-and-forget or
      scheduled on a background thread / task).
    - MAY be called concurrently for PRE_TOOL_USE in future versions when
      parallel tool execution is enabled (current implementation is sequential
      in registration order).

    Return semantics (see HookManager.fire and HookResult):
    - Return None or HookResult(decision="allow") to continue normally.
    - Return HookResult(decision="block", reason=...) (or raise HookVeto) to
      prevent execution (PRE) or to mark the result as blocked (POST).
    - For PRE_TOOL_USE: updated_args can rewrite the arguments passed to the tool.
    - For POST_TOOL_USE: additional_context is appended to the tool result
      content (structured error info is preserved). system_message can be used
      to inject into the conversation.

    Merge semantics when multiple callbacks are registered for the same event:
    - block: any block wins
    - reason / updated_args: last non-None wins
    - additional_context / system_message: concatenated (newlines)
    """

    PRE_TOOL_USE = "PreToolUse"      # Fired before each tool execution. Args: ToolCallContext
    POST_TOOL_USE = "PostToolUse"    # Fired after each tool execution. Args: ToolResultContext
    SESSION_START = "SessionStart"   # Fired once at session creation.
    SESSION_END = "SessionEnd"       # Fired on session termination.
    FINAL_ANSWER = "FinalAnswer"     # Fired when the agent produces a final answer.
    TURN_START = "TurnStart"         # Start of an agent turn/step.
    TURN_END = "TurnEnd"             # End of an agent turn/step (after tool or final).
    COMPACT = "Compact"              # Fired when context compaction occurs.
    ERROR = "Error"                  # Fired on unrecoverable / classified errors.


class HookVeto(Exception):
    """Backward-compatible block signal.

    New code should return ``HookResult(decision='block', reason=...)``.
    Raising ``HookVeto`` is still supported and gets mapped to the same
    structured result.
    """


@dataclass
class HookResult:
    """Result returned (or merged) from one or more hook callbacks.

    Fields:
        decision: "allow" (default) or "block".
        reason: Human-readable reason when blocking.
        updated_args: For PRE_TOOL_USE only — replacement args for the tool call.
        additional_context: Appended to the final ToolResult.content (POST).
        system_message: Can be injected as a system message in some contexts.

    When multiple callbacks fire for the same event, results are merged by
    HookManager (see _merge_results): block is OR, updated_args last-wins,
    contexts are concatenated.
    """

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
    """Central registry and dispatcher for lifecycle hook callbacks.

    Listeners are stored per event and called by fire(). The implementation
    deliberately swallows most exceptions from user callbacks (see fire docstring)
    so that a misbehaving hook cannot crash the whole agent session.

    This system is richer than pi's (9 events vs their 2 core hooks) but we
    adopted their strict contract language for documentation and future
    compatibility.
    """

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
        """Invoke all registered callbacks for the event and merge their results.

        Contract (pi-inspired, enforced here):
        - Callbacks are executed in the order they were .add()ed.
        - Any uncaught exception (other than HookVeto) is swallowed. The
          remaining listeners continue. This keeps the agent robust.
        - HookVeto (or HookResult with decision="block") short-circuits and
          returns immediately.
        - Results from all non-blocking listeners are merged (see HookResult
          and _merge_results docstrings).
        - Returns a HookResult (never raises to the caller, except during
          callback execution which we catch).

        For PRE_TOOL_USE the caller (ToolRegistry) will respect updated_args
        and blocked. For POST_TOOL_USE additional_context is injected into
        the tool result.
        """
        merged = HookResult()
        for callback in list(self._listeners.get(_key(event), [])):
            try:
                result = callback(context)
            except HookVeto as veto:
                return HookResult(decision="block", reason=str(veto))
            except Exception:
                # Per documented contract (borrowed from pi): callbacks must not
                # raise. Non-Veto exceptions are swallowed so one bad hook cannot
                # kill the agent loop. Later listeners for the same event still run.
                continue
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
