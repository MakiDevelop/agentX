from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentx.protocol import ToolResult
from agentx.safety import Risk


class HookEvent(str, Enum):
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"


class HookVeto(Exception):
    """Raised by a before_* hook to abort the pending action."""


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


HookCallback = Callable[[Any], None]


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

    def fire(self, event: HookEvent | str, context: Any) -> None:
        for callback in list(self._listeners.get(_key(event), [])):
            callback(context)


def _key(event: HookEvent | str) -> str:
    return event.value if isinstance(event, HookEvent) else event
