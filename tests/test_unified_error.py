from __future__ import annotations

from typing import Any

from agentx.protocol import ToolResult
from agentx.tools.registry import ToolRegistry
from agentx.safety import Risk


class _FailingTool:
    name = "fail_tool"
    description = "always fails"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        raise ValueError("bad input")


class _OkTool:
    name = "ok_tool"
    description = "always succeeds"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return "ok"


def test_tool_result_with_error_fields() -> None:
    r = ToolResult(tool="t", ok=False, content="err", error_type="ValueError", error_details={"key": "val"})
    assert r.error_type == "ValueError"
    assert r.error_details == {"key": "val"}


def test_tool_result_backward_compatible() -> None:
    r = ToolResult(tool="t", ok=True, content="ok")
    assert r.error_type is None
    assert r.error_details is None


def test_registry_populates_error_type_on_exception() -> None:
    registry = ToolRegistry([_FailingTool()], auto_approve_yellow=True)  # type: ignore[list-item]
    result = registry.run("fail_tool", {})
    assert not result.ok
    assert result.error_type == "ValueError"


def test_registry_no_error_type_on_success() -> None:
    registry = ToolRegistry([_OkTool()], auto_approve_yellow=True)  # type: ignore[list-item]
    result = registry.run("ok_tool", {})
    assert result.ok
    assert result.error_type is None


def test_error_details_survives_json_roundtrip() -> None:
    original = ToolResult(
        tool="t", ok=False, content="err",
        error_type="KeyError", error_details={"missing": "field_x"},
    )
    json_str = original.model_dump_json()
    restored = ToolResult.model_validate_json(json_str)
    assert restored.error_type == "KeyError"
    assert restored.error_details == {"missing": "field_x"}
