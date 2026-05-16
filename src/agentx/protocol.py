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


class Reflect(BaseModel):
    type: Literal["reflect"]
    focus: str | None = None  # 可選，告訴模型要特別反思哪個面向


class ToolResult(BaseModel):
    tool: str
    ok: bool
    content: str

