from pathlib import Path

from agentx.runtime_prompt import AGENT_SYSTEM_PROMPT, build_agent_system_prompt, build_chat_system_prompt


def test_chat_prompt_describes_agentx_runtime_without_generic_denial():
    prompt = build_chat_system_prompt(Path("/tmp/workspace"))

    assert "agentX CLI" in prompt
    assert "Use plain terminal text only" in prompt
    assert "Do not use Markdown formatting" in prompt
    assert "Current workspace: /tmp/workspace" in prompt
    assert "Do not say you have no local environment access" in prompt
    assert "小Ge" in prompt
    assert "nickname does not change" in prompt
    assert "create a Docker site" in prompt
    assert "Docker Compose ps/logs/build/up/down are available" in prompt
    assert "Docker push is not enabled" in prompt
    assert "Arbitrary SSH is not currently enabled" in prompt


def test_agent_prompt_states_ssh_limit_and_tool_evidence_rule():
    assert "Use plain terminal text for final answers" in AGENT_SYSTEM_PROMPT
    assert "Do not use Markdown formatting" in AGENT_SYSTEM_PROMPT
    assert "You may create Docker site files through approved patches" in AGENT_SYSTEM_PROMPT
    assert "docker_compose_up" in AGENT_SYSTEM_PROMPT
    assert "Docker push is not enabled" in AGENT_SYSTEM_PROMPT
    assert "小Ge" in AGENT_SYSTEM_PROMPT
    assert "You cannot run arbitrary shell commands or SSH" in AGENT_SYSTEM_PROMPT
    assert "Do not claim you used a tool unless the tool result is present" in AGENT_SYSTEM_PROMPT


def test_tutor_persona_is_injected_into_prompts():
    chat_prompt = build_chat_system_prompt(Path("/tmp/workspace"), "tutor")
    agent_prompt = build_agent_system_prompt("tutor")

    assert "女子大學生家庭教師模式" in chat_prompt
    assert "女子大學生家庭教師模式" in agent_prompt
    assert "不使用曖昧、戀愛、情色" in chat_prompt
