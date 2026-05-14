from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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

