from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agentx.hooks import (
    HookEvent,
    HookManager,
    HookVeto,
    ToolCallContext,
    ToolResultContext,
)
from agentx.protocol import Tool, ToolResult
from agentx.safety import Risk


ApprovalCallback = Callable[[str, dict[str, Any], Risk], bool]


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] | None = None,
        *,
        approver: ApprovalCallback | None = None,
        hooks: HookManager | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.approver = approver
        self.hooks = hooks
        if tools is not None:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def describe_tools(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self._tools.items()}

    def run(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool=name, ok=False, content=f"Unknown tool: {name}")
        if tool.risk == Risk.RED:
            return ToolResult(
                tool=name,
                ok=False,
                content=f"Tool is blocked by safety policy: {name}",
            )
        if tool.risk == Risk.YELLOW and self.approver is not None:
            if not self.approver(name, args, tool.risk):
                return ToolResult(
                    tool=name,
                    ok=False,
                    content=f"Rejected by approval gate: {name}",
                )
        if self.hooks is not None:
            try:
                self.hooks.fire(
                    HookEvent.BEFORE_TOOL_CALL,
                    ToolCallContext(tool=name, args=args, risk=tool.risk),
                )
            except HookVeto as veto:
                return ToolResult(
                    tool=name,
                    ok=False,
                    content=f"Vetoed by hook: {veto}",
                )
        try:
            content = tool.run(args)
            result = ToolResult(tool=name, ok=True, content=str(content))
        except Exception as exc:
            result = ToolResult(tool=name, ok=False, content=f"{type(exc).__name__}: {exc}")
        if self.hooks is not None:
            self.hooks.fire(
                HookEvent.AFTER_TOOL_CALL,
                ToolResultContext(tool=name, args=args, result=result),
            )
        return result
