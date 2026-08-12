"""The system prompt must describe the tools that actually exist.

A local model can only call what the prompt shows it, and reliably malforms
calls it was told to make but never given a signature for. Before the tool
section was generated from metadata, the hand-written list had drifted badly:

  - 11 registered tools were never taught: write_file, edit_file, run_command,
    run_build_command, web_fetch, git_push and all five docker_compose_* tools.
  - The prose said "When creating a NEW file, always use write_file" while the
    list never defined write_file at all.
  - search_replace was taught as a tool name; it is an alias of edit_file.

These tests make that class of drift impossible to reintroduce silently.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from agentx.runtime_prompt import (
    LOOP_PSEUDO_TOOLS,
    UNREADABLE_TOOLS_MARKER,
    build_agent_system_prompt,
    build_headless_agent_system_prompt,
    build_tools_section,
    build_worker_system_prompt,
)
from agentx.tools import ToolRegistry, builtin_tools


class _FakeMemory:
    def search(self, *args: object, **kwargs: object) -> str:
        return ""


@pytest.fixture
def registry() -> ToolRegistry:
    workspace = pathlib.Path(tempfile.mkdtemp())
    return ToolRegistry(builtin_tools(workspace, _FakeMemory()), auto_approve_yellow=True)  # type: ignore[arg-type]


def _prompt_variants(registry: ToolRegistry) -> dict[str, str]:
    """Every prompt a model can actually receive in agent mode."""
    return {
        "interactive": build_agent_system_prompt(tools=registry),
        "headless": build_headless_agent_system_prompt(tools=registry),
        "worker": build_worker_system_prompt("do the thing", tools=registry),
    }


def test_every_registered_tool_is_taught_in_every_agent_prompt(registry: ToolRegistry) -> None:
    for variant, prompt in _prompt_variants(registry).items():
        missing = [name for name in registry.names() if f"- {name}(" not in prompt]
        assert not missing, f"{variant} prompt does not teach: {missing}"


def test_prompt_teaches_the_calling_convention(registry: ToolRegistry) -> None:
    """Listing tools without showing how to call them is not teaching them."""
    for variant, prompt in _prompt_variants(registry).items():
        assert '"type":"tool_call"' in prompt, f"{variant} prompt omits the call format"


def test_prompt_never_teaches_a_tool_that_does_not_exist(registry: ToolRegistry) -> None:
    """No phantom tools: anything with a signature line must be callable."""
    import re

    real = set(registry.names())
    for tool in registry.tools():
        real |= set(getattr(tool, "aliases", []) or [])
    pseudo = {name for name, _sig, _desc in LOOP_PSEUDO_TOOLS}

    for variant, prompt in _prompt_variants(registry).items():
        taught = set(re.findall(r"^- ([a-z_][a-z0-9_]*)\(", prompt, re.MULTILINE))
        phantom = taught - real - pseudo
        assert not phantom, f"{variant} prompt teaches non-existent tools: {sorted(phantom)}"


def test_write_and_edit_tools_are_both_present(registry: ToolRegistry) -> None:
    """The specific contradiction that motivated this: prose referenced a tool
    the list never defined."""
    for variant, prompt in _prompt_variants(registry).items():
        assert "- write_file(" in prompt, f"{variant} prompt lacks write_file"
        assert "- edit_file(" in prompt, f"{variant} prompt lacks edit_file"


def test_aliases_are_shown_against_their_canonical_tool(registry: ToolRegistry) -> None:
    section = build_tools_section(registry)
    assert "- edit_file(" in section
    assert "search_replace" in section
    # The alias must not masquerade as a tool in its own right.
    assert "- search_replace(" not in section


def test_risk_tiers_are_part_of_the_calling_contract(registry: ToolRegistry) -> None:
    """The model must know a YELLOW call can be refused."""
    section = build_tools_section(registry)
    assert "GREEN — runs immediately" in section
    # Split on the header, not the bare word: tool descriptions mention "YELLOW"
    # too (run_build_command explains why it is YELLOW).
    green_block, yellow_block = section.split("YELLOW — requires approval", 1)

    assert "- write_file(" in yellow_block, "write_file must be gated"
    assert "- git_push(" in yellow_block, "git_push must be gated"
    assert "- read_file(" in green_block, "read_file must not need approval"


def test_loop_pseudo_tools_are_taught(registry: ToolRegistry) -> None:
    """task_* are handled by AgentSession, not the registry, but the model still
    needs them documented."""
    section = build_tools_section(registry)
    for name, _sig, _desc in LOOP_PSEUDO_TOOLS:
        assert f"- {name}(" in section


def test_default_prompt_matches_the_builtin_tools(registry: ToolRegistry) -> None:
    """With no registry passed, the section is derived from the tool classes and
    must still cover everything builtin_tools() registers."""
    section = build_tools_section(None)
    missing = [name for name in registry.names() if f"- {name}(" not in section]
    assert not missing, f"default prompt does not teach: {missing}"


def test_restricted_registry_does_not_advertise_unregistered_tools() -> None:
    """A caller that registers fewer tools must not get the full builtin list."""

    class _Only:
        name = "only_tool"
        description = "the only tool"
        signature = "x"
        from agentx.safety import Risk

        risk = Risk.GREEN

        def run(self, args: dict[str, object]) -> str:
            return "ok"

    section = build_tools_section(ToolRegistry([_Only()]))  # type: ignore[list-item]
    assert "- only_tool(x)" in section
    assert "write_file" not in section
    assert "list_files" not in section


def test_unreadable_registry_is_loud_not_silently_stale() -> None:
    """The old code fell back to a stale hand-written list on any exception,
    which is how the drift survived. An unreadable registry must be visible."""
    section = build_tools_section(object())  # type: ignore[arg-type]

    assert section == UNREADABLE_TOOLS_MARKER
    assert "write_file" not in section


def test_real_registry_never_produces_the_unreadable_marker(registry: ToolRegistry) -> None:
    for variant, prompt in _prompt_variants(registry).items():
        assert UNREADABLE_TOOLS_MARKER not in prompt, f"{variant} could not read the registry"
