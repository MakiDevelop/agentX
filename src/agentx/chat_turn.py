"""Structured model-turn result.

Backends used to return only a content string. That forced every model
through a JSON-in-text protocol even when the runtime already had a native
tool-calling API. ChatTurn is the common shape both Ollama and llama.cpp
can fill, and AgentSession can consume without knowing which backend ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NativeToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatTurn:
    content: str = ""
    tool_calls: tuple[NativeToolCall, ...] = ()

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
