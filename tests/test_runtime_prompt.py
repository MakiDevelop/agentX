from pathlib import Path

from agentx.runtime_prompt import AGENT_SYSTEM_PROMPT, build_chat_system_prompt


def test_chat_prompt_describes_agentx_runtime_without_generic_denial():
    prompt = build_chat_system_prompt(Path("/tmp/workspace"))

    assert "agentX CLI" in prompt
    assert "Current workspace: /tmp/workspace" in prompt
    assert "Do not say you have no local environment access" in prompt
    assert "Arbitrary SSH is not currently enabled" in prompt


def test_agent_prompt_states_ssh_limit_and_tool_evidence_rule():
    assert "You cannot run arbitrary shell commands or SSH" in AGENT_SYSTEM_PROMPT
    assert "Do not claim you used a tool unless the tool result is present" in AGENT_SYSTEM_PROMPT
