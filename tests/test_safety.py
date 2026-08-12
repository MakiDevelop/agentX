"""Tests for the risk model that is actually enforced at runtime.

Risk is declared per-Tool (`Tool.risk`) and enforced in exactly one place:
`ToolRegistry.run()`. Shell access is exact-match allowlisted in
`agentx.tools._helpers`. These tests guard those two mechanisms.

History: this file previously asserted against `safety.classify_tool` /
`safety.classify_command`, a parallel risk table that no production code ever
called. By the time it was removed, 6 of 33 tools disagreed with it (write_file
and edit_file were classified RED there while really being YELLOW). Testing a
table nothing consults produced green runs that proved nothing — hence these
tests drive the registry and the tools themselves.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from agentx.protocol import Tool, ToolResult
from agentx.safety import Risk
from agentx.tools import builtin
from agentx.tools._helpers import ALLOWED_COMMANDS, BUILD_COMMANDS
from agentx.tools.registry import ToolRegistry


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> ToolResult:
    """registry.run() returns a union; narrow it for the plain call form."""
    result = registry.run(name, args)
    assert isinstance(result, ToolResult)
    return result


def _builtin_tool_classes() -> list[type]:
    return [
        obj
        for obj in vars(builtin).values()
        if inspect.isclass(obj)
        and isinstance(getattr(obj, "name", None), str)
        and hasattr(obj, "risk")
    ]


def _stub_tool(name: str, risk: Risk) -> Tool:
    class _Stub:
        def __init__(self) -> None:
            self.name = name
            self.description = "stub"
            self.risk = risk
            self.ran = False

        def run(self, args: dict[str, Any]) -> str:  # noqa: ARG002
            self.ran = True
            return "ok"

    return _Stub()  # type: ignore[return-value]


# --- Risk declarations -------------------------------------------------------


def test_every_builtin_tool_declares_a_known_risk_tier() -> None:
    classes = _builtin_tool_classes()
    assert classes, "no builtin tool classes discovered"
    for cls in classes:
        assert isinstance(cls.risk, Risk), f"{cls.__name__}.risk is not a Risk enum"


def test_builtin_tool_risk_is_the_single_source_of_truth() -> None:
    """There must be no second risk table to drift out of sync with."""
    import agentx.safety as safety_module

    exported = {name for name in vars(safety_module) if not name.startswith("_")}
    assert "classify_tool" not in exported
    assert "classify_command" not in exported
    assert "require_allowed" not in exported
    assert "READ_ONLY_TOOLS" not in exported
    assert "RED_COMMAND_PATTERNS" not in exported


def test_write_and_push_tools_are_gated_not_green() -> None:
    by_name = {cls.name: cls.risk for cls in _builtin_tool_classes()}
    for name in ("write_file", "edit_file", "insert_code", "apply_patch", "git_push"):
        assert by_name[name] is not Risk.GREEN, f"{name} must not run without approval"


# --- Registry enforcement ----------------------------------------------------


def test_registry_never_executes_a_red_tool() -> None:
    tool = _stub_tool("dangerous", Risk.RED)
    registry = ToolRegistry([tool], auto_approve_yellow=True)

    result = _run(registry, "dangerous", {})

    assert result.ok is False
    assert "blocked by safety policy" in result.content.lower()
    assert tool.ran is False  # type: ignore[attr-defined]


def test_registry_fails_closed_for_yellow_without_approver() -> None:
    tool = _stub_tool("writes", Risk.YELLOW)
    registry = ToolRegistry([tool])

    result = _run(registry, "writes", {})

    assert result.ok is False
    assert "requires explicit approval" in result.content
    assert tool.ran is False  # type: ignore[attr-defined]


def test_registry_respects_a_rejecting_approver() -> None:
    tool = _stub_tool("writes", Risk.YELLOW)
    registry = ToolRegistry([tool], approver=lambda _name, _args, _risk: False)

    result = _run(registry, "writes", {})

    assert result.ok is False
    assert "Rejected by approval gate" in result.content
    assert tool.ran is False  # type: ignore[attr-defined]


def test_registry_runs_green_tools_without_approval() -> None:
    tool = _stub_tool("reads", Risk.GREEN)
    registry = ToolRegistry([tool])

    result = _run(registry, "reads", {})

    assert result.ok is True
    assert tool.ran is True  # type: ignore[attr-defined]


# --- Command allowlists ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp/demo",
        "cat ~/.ssh/config",
        "git push --force",
        "ls; rm -rf .",
        "ls -la && cat /etc/passwd",
        "ls$(whoami)",
        "uv run pytest -q --collect-only",  # prefix of an allowlisted entry
    ],
)
def test_run_command_rejects_anything_not_literally_allowlisted(
    tmp_path: Path, command: str
) -> None:
    tool = builtin.RunCommandTool(tmp_path)

    with pytest.raises(PermissionError):
        tool.run({"command": command})


def test_run_build_command_rejects_non_allowlisted(tmp_path: Path) -> None:
    tool = builtin.RunBuildCommandTool(tmp_path)

    with pytest.raises(PermissionError):
        tool.run({"command": "cargo test --features danger"})


def test_allowlists_are_disjoint() -> None:
    """A command must not be reachable at two different risk tiers."""
    assert not (set(ALLOWED_COMMANDS) & set(BUILD_COMMANDS))


@pytest.mark.parametrize("table", [ALLOWED_COMMANDS, BUILD_COMMANDS])
def test_allowlisted_commands_are_argv_lists_without_shell_escapes(
    table: dict[str, list[str]],
) -> None:
    """Entries are execed as argv (shell=False); guard against a shell being
    smuggled in, which would turn the allowlist into arbitrary execution."""
    for label, argv in table.items():
        assert isinstance(argv, list) and argv, f"{label!r} must map to a non-empty argv list"
        assert argv[0] not in {"sh", "bash", "zsh", "eval", "env"}, f"{label!r} spawns a shell"
        for part in argv:
            assert isinstance(part, str)
            assert not any(ch in part for ch in ";|&`$><"), f"{label!r} contains a shell metachar"


def test_run_command_is_green_only_because_it_is_allowlisted(tmp_path: Path) -> None:
    """run_command is GREEN, so nothing gates it but the allowlist itself."""
    tool = builtin.RunCommandTool(tmp_path)
    assert tool.risk is Risk.GREEN
    assert set(ALLOWED_COMMANDS), "an empty allowlist would make GREEN meaningless"
