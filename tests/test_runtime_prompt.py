from pathlib import Path

from agentx.runtime_prompt import AGENT_SYSTEM_PROMPT, build_agent_system_prompt, build_chat_system_prompt


def test_chat_prompt_describes_agentx_runtime_without_generic_denial():
    prompt = build_chat_system_prompt(Path("/tmp/workspace"))

    assert "agentX CLI" in prompt
    assert "Use plain terminal text only" in prompt
    assert "Do not use Markdown formatting" in prompt
    assert "Current workspace: /tmp/workspace" in prompt
    assert "Do not say you have no local environment access" in prompt
    assert "/fetch" in prompt
    assert "Do not claim broad web browsing or search" in prompt
    assert "小Ge" in prompt
    assert "nickname does not change" in prompt
    assert "create a Docker site" in prompt
    assert "Docker Compose ps/logs/build/up/down are available" in prompt
    assert "Docker push is not enabled" in prompt
    assert "Arbitrary SSH is not currently enabled" in prompt


def test_agent_prompt_states_ssh_limit_and_tool_evidence_rule():
    """驗證新版 agent prompt 的核心原則是否正確（配合 Micro-task 15 大改寫）。"""
    assert "search_replace" in AGENT_SYSTEM_PROMPT
    assert "insert_code" in AGENT_SYSTEM_PROMPT
    assert "小Ge" in AGENT_SYSTEM_PROMPT
    assert "arbitrary shell commands" in AGENT_SYSTEM_PROMPT or "You cannot run arbitrary" in AGENT_SYSTEM_PROMPT
    assert "Do not overclaim progress" in AGENT_SYSTEM_PROMPT
    assert "安全優先" in AGENT_SYSTEM_PROMPT or "Safety first" in AGENT_SYSTEM_PROMPT
    assert "逐檔 stage" in AGENT_SYSTEM_PROMPT or "逐檔" in AGENT_SYSTEM_PROMPT
    assert "Small steps" in AGENT_SYSTEM_PROMPT or "小步驟" in AGENT_SYSTEM_PROMPT
    assert "中文 commit" in AGENT_SYSTEM_PROMPT
    assert "engineering agent" in AGENT_SYSTEM_PROMPT.lower() or "local engineering agent" in AGENT_SYSTEM_PROMPT.lower()


def test_tutor_persona_is_injected_into_prompts():
    chat_prompt = build_chat_system_prompt(Path("/tmp/workspace"), "tutor")
    agent_prompt = build_agent_system_prompt("tutor")

    assert "女子大學生家庭教師模式" in chat_prompt
    assert "女子大學生家庭教師模式" in agent_prompt
    assert "不使用曖昧、戀愛、情色" in chat_prompt
