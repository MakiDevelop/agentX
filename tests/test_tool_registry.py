from typing import Any

from agentx.protocol import Risk
from agentx.tools import ToolRegistry


class EchoTool:
    name = "echo"
    description = "echoes the args back"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return str(args)


class BoomTool:
    name = "boom"
    description = "always raises"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        raise RuntimeError("kaboom")


class DangerTool:
    name = "danger"
    description = "blocked by safety policy"
    risk = Risk.RED

    def run(self, args: dict[str, Any]) -> str:
        return "ran"


class YellowTool:
    name = "yellow"
    description = "needs approval"
    risk = Risk.YELLOW

    def run(self, args: dict[str, Any]) -> str:
        return "done"


def test_register_and_run_returns_ok() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = registry.run("echo", {"value": 1})
    assert result.ok
    assert "value" in result.content


def test_unknown_tool_is_not_ok() -> None:
    result = ToolRegistry().run("missing", {})
    assert not result.ok
    assert "Unknown" in result.content


def test_red_tool_is_blocked() -> None:
    registry = ToolRegistry([DangerTool()])
    result = registry.run("danger", {})
    assert not result.ok
    assert "blocked" in result.content.lower()


def test_yellow_tool_requires_approval() -> None:
    calls: list[tuple[str, dict[str, Any], Risk]] = []

    def approve(name: str, args: dict[str, Any], risk: Risk) -> bool:
        calls.append((name, args, risk))
        return False

    registry = ToolRegistry([YellowTool()], approver=approve)
    result = registry.run("yellow", {"k": 1})
    assert not result.ok
    assert "approval" in result.content.lower()
    assert calls == [("yellow", {"k": 1}, Risk.YELLOW)]


def test_yellow_tool_runs_when_approved() -> None:
    registry = ToolRegistry([YellowTool()], approver=lambda *_: True)
    result = registry.run("yellow", {})
    assert result.ok
    assert result.content == "done"


def test_exception_is_captured_as_failure() -> None:
    registry = ToolRegistry([BoomTool()])
    result = registry.run("boom", {})
    assert not result.ok
    assert "RuntimeError" in result.content


def test_unregister_removes_tool() -> None:
    registry = ToolRegistry([EchoTool()])
    registry.unregister("echo")
    result = registry.run("echo", {})
    assert not result.ok


def test_describe_tools_lists_registered() -> None:
    registry = ToolRegistry([EchoTool(), BoomTool()])
    described = registry.describe_tools()
    assert set(described) == {"echo", "boom"}
