from typing import Any

from agentx.hooks import (
    HookEvent,
    HookManager,
    HookVeto,
    ToolCallContext,
    ToolResultContext,
)
from agentx.protocol import Risk
from agentx.tools import ToolRegistry


class EchoTool:
    name = "echo"
    description = "echo"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return f"echo:{args.get('value', '')}"


def test_before_and_after_tool_call_observe() -> None:
    seen: list[tuple[str, Any]] = []
    hooks = HookManager()
    hooks.add(HookEvent.BEFORE_TOOL_CALL, lambda ctx: seen.append(("before", ctx)))
    hooks.add(HookEvent.AFTER_TOOL_CALL, lambda ctx: seen.append(("after", ctx)))

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {"value": "hi"})

    assert result.ok
    assert [event for event, _ in seen] == ["before", "after"]
    before_ctx = seen[0][1]
    after_ctx = seen[1][1]
    assert isinstance(before_ctx, ToolCallContext)
    assert before_ctx.tool == "echo"
    assert before_ctx.risk == Risk.GREEN
    assert isinstance(after_ctx, ToolResultContext)
    assert after_ctx.result.ok
    assert after_ctx.result.content == "echo:hi"


def test_before_tool_call_veto_blocks_run() -> None:
    after_calls: list[ToolResultContext] = []
    hooks = HookManager()

    def veto(ctx: ToolCallContext) -> None:
        raise HookVeto(f"blocked {ctx.tool}")

    hooks.add(HookEvent.BEFORE_TOOL_CALL, veto)
    hooks.add(HookEvent.AFTER_TOOL_CALL, after_calls.append)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {})

    assert not result.ok
    assert "Vetoed by hook" in result.content
    assert after_calls == []


def test_remove_hook_stops_firing() -> None:
    calls: list[str] = []

    def callback(ctx: ToolCallContext) -> None:
        calls.append(ctx.tool)

    hooks = HookManager()
    hooks.add(HookEvent.BEFORE_TOOL_CALL, callback)
    hooks.remove(HookEvent.BEFORE_TOOL_CALL, callback)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    registry.run("echo", {})

    assert calls == []
