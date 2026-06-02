from typing import Any

from agentx.protocol import Risk
from agentx.runtime_prompt import build_agent_system_prompt
from agentx.tools import ToolRegistry


class CustomTool:
    name = "do_thing"
    description = "do a thing"
    risk = Risk.GREEN
    signature = "target"

    def run(self, args: dict[str, Any]) -> str:
        return "ok"


class DisabledTool:
    name = "offline"
    description = "offline tool"
    risk = Risk.GREEN

    def is_enabled(self) -> bool:
        return False

    def run(self, args: dict[str, Any]) -> str:
        return ""


def test_prompt_uses_default_tool_lines_when_no_registry() -> None:
    prompt = build_agent_system_prompt()
    assert "list_files" in prompt
    assert "memory_search" in prompt


def test_prompt_lists_registry_tools_with_signature() -> None:
    registry = ToolRegistry([CustomTool()])
    prompt = build_agent_system_prompt(tools=registry)
    assert "- do_thing(target) — do a thing" in prompt
    assert "list_files" not in prompt


def test_prompt_skips_disabled_tools() -> None:
    registry = ToolRegistry([CustomTool(), DisabledTool()])
    prompt = build_agent_system_prompt(tools=registry)
    assert "do_thing" in prompt
    assert "offline" not in prompt


def test_prompt_handles_empty_registry() -> None:
    prompt = build_agent_system_prompt(tools=ToolRegistry())
    assert "(no tools registered)" in prompt
