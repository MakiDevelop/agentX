from typing import Any

from agentx.hooks import (
    HookEvent,
    HookManager,
    HookResult,
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


def test_pre_and_post_hook_observe() -> None:
    seen: list[tuple[str, Any]] = []
    hooks = HookManager()
    hooks.add(HookEvent.PRE_TOOL_USE, lambda ctx: seen.append(("pre", ctx)))
    hooks.add(HookEvent.POST_TOOL_USE, lambda ctx: seen.append(("post", ctx)))

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {"value": "hi"})

    assert result.ok
    assert [event for event, _ in seen] == ["pre", "post"]
    pre_ctx = seen[0][1]
    post_ctx = seen[1][1]
    assert isinstance(pre_ctx, ToolCallContext)
    assert pre_ctx.tool == "echo"
    assert pre_ctx.risk == Risk.GREEN
    assert isinstance(post_ctx, ToolResultContext)
    assert post_ctx.result.ok
    assert post_ctx.result.content == "echo:hi"


def test_hook_result_block_stops_run() -> None:
    after_calls: list[ToolResultContext] = []
    hooks = HookManager()
    hooks.add(
        HookEvent.PRE_TOOL_USE,
        lambda ctx: HookResult(decision="block", reason=f"blocked {ctx.tool}"),
    )
    hooks.add(HookEvent.POST_TOOL_USE, after_calls.append)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    result = registry.run("echo", {})

    assert not result.ok
    assert "Blocked by hook" in result.content
    assert "blocked echo" in result.content
    assert after_calls == []


def test_hook_veto_still_blocks_via_compat() -> None:
    hooks = HookManager()

    def veto(ctx: ToolCallContext) -> None:
        raise HookVeto("legacy ban")

    hooks.add(HookEvent.PRE_TOOL_USE, veto)
    registry = ToolRegistry([EchoTool()], hooks=hooks)

    result = registry.run("echo", {})
    assert not result.ok
    assert "Blocked by hook" in result.content
    assert "legacy ban" in result.content


def test_hook_can_modify_args() -> None:
    hooks = HookManager()

    def redact(ctx: ToolCallContext) -> HookResult:
        return HookResult(updated_args={**ctx.args, "value": "REDACTED"})

    hooks.add(HookEvent.PRE_TOOL_USE, redact)
    registry = ToolRegistry([EchoTool()], hooks=hooks)

    result = registry.run("echo", {"value": "secret"})
    assert result.ok
    assert result.content == "echo:REDACTED"


def test_pre_hook_updates_args_before_yellow_approval() -> None:
    seen: list[dict[str, Any]] = []
    hooks = HookManager()

    def update_args(ctx: ToolCallContext) -> HookResult:
        return HookResult(updated_args={**ctx.args, "value": "final"})

    def approve(name: str, args: dict[str, Any], risk: Risk) -> bool:
        seen.append(args)
        return True

    hooks.add(HookEvent.PRE_TOOL_USE, update_args)
    registry = ToolRegistry([YellowEchoTool()], approver=approve, hooks=hooks)

    result = registry.run("yellow_echo", {"value": "original"})

    assert result.ok
    assert result.content == "yellow:final"
    assert seen == [{"value": "final"}]


def test_post_hook_can_block_result() -> None:
    hooks = HookManager()
    hooks.add(
        HookEvent.POST_TOOL_USE,
        lambda ctx: HookResult(decision="block", reason=f"bad {ctx.tool}"),
    )
    registry = ToolRegistry([EchoTool()], hooks=hooks)

    result = registry.run("echo", {"value": "hi"})

    assert not result.ok
    assert result.content == "Blocked by post hook: bad echo"


def test_post_hook_additional_context_is_visible() -> None:
    hooks = HookManager()
    hooks.add(
        HookEvent.POST_TOOL_USE,
        lambda ctx: HookResult(additional_context="audit note"),
    )
    registry = ToolRegistry([EchoTool()], hooks=hooks)

    result = registry.run("echo", {"value": "hi"})

    assert result.ok
    assert "echo:hi" in result.content
    assert "Additional context:" in result.content
    assert "audit note" in result.content


def test_hooks_chain_in_order_and_short_circuit_on_block() -> None:
    fired: list[str] = []
    hooks = HookManager()

    def first(ctx: ToolCallContext) -> None:
        fired.append("first")

    def block(ctx: ToolCallContext) -> HookResult:
        fired.append("block")
        return HookResult(decision="block", reason="nope")

    def never(ctx: ToolCallContext) -> None:
        fired.append("never")

    hooks.add(HookEvent.PRE_TOOL_USE, first)
    hooks.add(HookEvent.PRE_TOOL_USE, block)
    hooks.add(HookEvent.PRE_TOOL_USE, never)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    registry.run("echo", {})

    assert fired == ["first", "block"]


def test_remove_hook_stops_firing() -> None:
    calls: list[str] = []

    def callback(ctx: ToolCallContext) -> None:
        calls.append(ctx.tool)

    hooks = HookManager()
    hooks.add(HookEvent.PRE_TOOL_USE, callback)
    hooks.remove(HookEvent.PRE_TOOL_USE, callback)

    registry = ToolRegistry([EchoTool()], hooks=hooks)
    registry.run("echo", {})

    assert calls == []


def test_event_values_match_claude_code() -> None:
    assert HookEvent.PRE_TOOL_USE.value == "PreToolUse"
    assert HookEvent.POST_TOOL_USE.value == "PostToolUse"


class YellowEchoTool:
    name = "yellow_echo"
    description = "yellow echo"
    risk = Risk.YELLOW

    def run(self, args: dict[str, Any]) -> str:
        return f"yellow:{args.get('value', '')}"
