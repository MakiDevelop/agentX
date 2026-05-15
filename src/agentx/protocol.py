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
    """Contract for a tool that the agent can call.

    Required members
    ----------------
    name : str
        Stable lookup key. Must be unique inside a ToolRegistry.
    description : str
        Short Chinese description shown to the model and in /tools.
    risk : Risk
        Safety classification (GREEN / YELLOW / RED). YELLOW invokes the
        approval gate; RED is always blocked.
    run(args) -> str
        Execute the tool with the model-provided ``args`` dict and return
        the result string. Raising propagates as ``ok=False`` in the
        wrapped ToolResult.

    Optional members
    ----------------
    Helpers in ``agentx.tools.registry`` access these via ``getattr`` with
    sane defaults — implementers may declare any subset:

    aliases : list[str]
        Alternate names the tool can be looked up by. Default: ``[]``.
    signature : str
        Args signature shown in the agent system prompt
        (e.g. ``"path, max_chars=20000"``). Default: ``""``.
    is_enabled() -> bool
        Runtime gate; ``False`` hides the tool from listings and makes
        ``ToolRegistry.run`` return a failure. Default: always ``True``.
    prompt() -> str
        Custom system-prompt line for this tool. Default: auto-generated
        from ``signature`` + ``description`` via ``tool_prompt_line``.

    These extras are documented here rather than declared as Protocol
    attributes so a tool object that only sets the four required members
    still satisfies ``isinstance(x, Tool)``.
    """

    name: str
    description: str
    risk: Risk

    def run(self, args: dict[str, Any]) -> str: ...
