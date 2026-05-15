from typing import Any

from agentx.protocol import Risk
from agentx.tools import ToolRegistry, tool_prompt_line


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


class AliasTool:
    name = "primary"
    description = "primary tool"
    risk = Risk.GREEN
    aliases = ("alt", "p")

    def run(self, args: dict[str, Any]) -> str:
        return "ran primary"


def test_aliases_resolve_to_primary() -> None:
    registry = ToolRegistry([AliasTool()])
    assert registry.get("primary") is not None
    assert registry.get("alt") is registry.get("primary")
    assert registry.run("alt", {}).ok
    assert registry.run("p", {}).ok


def test_describe_tools_only_shows_primary_names() -> None:
    registry = ToolRegistry([AliasTool()])
    described = registry.describe_tools()
    assert set(described) == {"primary"}


def test_unregister_by_alias_removes_tool() -> None:
    registry = ToolRegistry([AliasTool()])
    registry.unregister("alt")
    assert registry.get("primary") is None
    assert registry.get("alt") is None


class OtherAliasTool:
    name = "other"
    description = "other tool"
    risk = Risk.GREEN
    aliases = ("primary",)

    def run(self, args: dict[str, Any]) -> str:
        return "ran other"


class ReplacedAliasTool:
    name = "primary"
    description = "replacement"
    risk = Risk.GREEN
    aliases = ("new",)

    def run(self, args: dict[str, Any]) -> str:
        return "ran replacement"


def test_register_rejects_alias_conflict_with_primary_name() -> None:
    registry = ToolRegistry([AliasTool()])
    try:
        registry.register(OtherAliasTool())
    except ValueError as exc:
        assert "conflicts" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected alias conflict")


def test_register_replaces_same_name_and_clears_stale_aliases() -> None:
    registry = ToolRegistry([AliasTool()])
    registry.register(ReplacedAliasTool())

    assert registry.get("primary") is not None
    assert registry.get("alt") is None
    assert registry.get("p") is None
    assert registry.run("new", {}).content == "ran replacement"


class DisabledTool:
    name = "off"
    description = "off in this env"
    risk = Risk.GREEN

    def is_enabled(self) -> bool:
        return False

    def run(self, args: dict[str, Any]) -> str:
        return "should not run"


def test_disabled_tool_run_returns_failure() -> None:
    registry = ToolRegistry([DisabledTool()])
    result = registry.run("off", {})
    assert not result.ok
    assert "disabled" in result.content.lower()


def test_disabled_tool_hidden_from_describe_and_names() -> None:
    registry = ToolRegistry([EchoTool(), DisabledTool()])
    assert "off" not in registry.names()
    assert "off" not in registry.describe_tools()


class SignatureTool:
    name = "sig"
    description = "with signature"
    risk = Risk.GREEN
    signature = "x, y=1"

    def run(self, args: dict[str, Any]) -> str:
        return ""


def test_tool_prompt_line_uses_signature() -> None:
    line = tool_prompt_line(SignatureTool())
    assert line == "- sig(x, y=1) — with signature"


def test_tool_prompt_line_falls_back_to_description() -> None:
    line = tool_prompt_line(EchoTool())
    assert line == "- echo — echoes the args back"


class CustomPromptTool:
    name = "custom"
    description = "fallback desc"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return ""

    def prompt(self) -> str:
        return "## custom block"


def test_tool_prompt_line_uses_custom_prompt() -> None:
    assert tool_prompt_line(CustomPromptTool()) == "## custom block"
