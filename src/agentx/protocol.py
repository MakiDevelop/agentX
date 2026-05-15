from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from agentx.safety import Risk


class ToolCall(BaseModel):
    type: Literal["tool_call"]
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class FinalAnswer(BaseModel):
    type: Literal["final"]
    content: str


class ToolResult(BaseModel):
    tool: str
    ok: bool
    content: str


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    risk: Risk

    def run(self, args: dict[str, Any]) -> str: ...
