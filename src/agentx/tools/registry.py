from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agentx.hooks import HookEvent, HookManager, ToolCallContext, ToolResultContext
from agentx.protocol import Tool, ToolResult
from agentx.safety import Risk


ApprovalCallback = Callable[[str, dict[str, Any], Risk], bool]


def tool_aliases(tool: Tool) -> list[str]:
    return list(getattr(tool, "aliases", []) or [])


def tool_is_enabled(tool: Tool) -> bool:
    is_enabled = getattr(tool, "is_enabled", None)
    if callable(is_enabled):
        return bool(is_enabled())
    if is_enabled is None:
        return True
    return bool(is_enabled)


def tool_signature(tool: Tool) -> str:
    return str(getattr(tool, "signature", "") or "")


def tool_prompt_line(tool: Tool) -> str:
    custom_prompt = getattr(tool, "prompt", None)
    if callable(custom_prompt):
        return str(custom_prompt())
    sig = tool_signature(tool)
    head = f"{tool.name}({sig})" if sig else tool.name
    return f"- {head} — {tool.description}"


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] | None = None,
        *,
        approver: ApprovalCallback | None = None,
        auto_approve_yellow: bool = False,
        hooks: HookManager | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}
        self.approver = approver
        self.auto_approve_yellow = auto_approve_yellow
        self.hooks = hooks
        if tools is not None:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        aliases = tool_aliases(tool)
        if tool.name in self._tools:
            self.unregister(tool.name)
        elif tool.name in self._aliases:
            owner = self._aliases[tool.name]
            raise ValueError(f"tool name conflicts with alias: {tool.name} -> {owner}")
        for alias in aliases:
            if alias in self._tools:
                raise ValueError(f"tool alias conflicts with tool name: {alias}")
            if alias in self._aliases:
                owner = self._aliases[alias]
                raise ValueError(f"tool alias conflicts with alias: {alias} -> {owner}")
        self._tools[tool.name] = tool
        for alias in aliases:
            self._aliases[alias] = tool.name

    def unregister(self, name: str) -> None:
        primary = self._aliases.pop(name, name)
        tool = self._tools.pop(primary, None)
        if tool is None:
            return
        for alias in tool_aliases(tool):
            self._aliases.pop(alias, None)

    def get(self, name: str) -> Tool | None:
        primary = self._aliases.get(name, name)
        return self._tools.get(primary)

    def names(self) -> list[str]:
        return [name for name, tool in self._tools.items() if tool_is_enabled(tool)]

    def tools(self) -> list[Tool]:
        return [tool for tool in self._tools.values() if tool_is_enabled(tool)]

    def describe_tools(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self._tools.items() if tool_is_enabled(tool)}

    def run(self, name: str, args: dict[str, Any]) -> ToolResult:
        primary = self._aliases.get(name, name)
        tool = self._tools.get(primary)
        if tool is None:
            return ToolResult(tool=name, ok=False, content=f"Unknown tool: {name}")
        if not tool_is_enabled(tool):
            return ToolResult(
                tool=name,
                ok=False,
                content=f"Tool disabled in this environment: {primary}",
            )
        if tool.risk == Risk.RED:
            return ToolResult(
                tool=name,
                ok=False,
                content=f"Tool is blocked by safety policy: {name}",
            )
        if self.hooks is not None:
            pre = self.hooks.fire(
                HookEvent.PRE_TOOL_USE,
                ToolCallContext(tool=primary, args=args, risk=tool.risk),
            )
            if pre.blocked:
                reason = pre.reason or "no reason given"
                return ToolResult(
                    tool=name,
                    ok=False,
                    content=f"Blocked by hook: {reason}",
                )
            if pre.updated_args is not None:
                args = pre.updated_args
        if tool.risk == Risk.YELLOW:
            if self.approver is not None:
                if not self.approver(primary, args, tool.risk):
                    return ToolResult(
                        tool=name,
                        ok=False,
                        content=f"Rejected by approval gate: {primary}",
                    )
            elif not self.auto_approve_yellow:
                return ToolResult(
                    tool=name,
                    ok=False,
                    content=(
                        f"YELLOW tool {primary!r} requires explicit approval but no "
                        "approver is configured (fail-closed). Pass approver=... or "
                        "auto_approve_yellow=True when constructing ToolRegistry."
                    ),
                )
        try:
            content = tool.run(args)
            result = ToolResult(tool=primary, ok=True, content=str(content))
        except Exception as exc:
            result = ToolResult(tool=primary, ok=False, content=f"{type(exc).__name__}: {exc}")
        if self.hooks is not None:
            post = self.hooks.fire(
                HookEvent.POST_TOOL_USE,
                ToolResultContext(tool=primary, args=args, result=result),
            )
            if post.blocked:
                reason = post.reason or "no reason given"
                return ToolResult(
                    tool=primary,
                    ok=False,
                    content=f"Blocked by post hook: {reason}",
                )
            if post.additional_context:
                result = ToolResult(
                    tool=result.tool,
                    ok=result.ok,
                    content=f"{result.content}\n\nAdditional context:\n{post.additional_context}",
                )
        return result
