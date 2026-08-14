from test_cli_runtime_handlers import _state

from agentx.cli_runtime_handlers import maybe_escalate_to_agent
from agentx.intent_route import should_use_agent


def test_should_use_agent_for_crawler_and_write() -> None:
    assert should_use_agent("我想請你寫一支專門爬取 https://erika.chibakuma.com/ 的爬蟲")
    assert should_use_agent("幫我改這個 bug")
    assert should_use_agent("implement the login handler")


def test_should_use_agent_stays_in_chat_for_questions() -> None:
    assert should_use_agent("你是誰") is False
    assert should_use_agent("什麼是 Memory Hall") is False
    assert should_use_agent("為什麼要寫測試") is False
    assert should_use_agent("") is False


def test_maybe_escalate_switches_chat_and_carries_history(tmp_path) -> None:  # noqa: ANN001
    state = _state(tmp_path, mode="chat")
    chat_messages = [
        {"role": "user", "content": "我想請你寫一支專門爬取 https://erika.chibakuma.com/ 的爬蟲"},
        {"role": "assistant", "content": "請先切換 agent"},
    ]
    switched = maybe_escalate_to_agent(state, chat_messages[0]["content"], chat_messages)
    assert switched is True
    assert state.mode == "agent"
    carried = " ".join(m.get("content", "") for m in state.agent_session.messages)
    assert "erika.chibakuma.com" in carried


def test_maybe_escalate_skips_when_already_agent_or_chat_question(tmp_path) -> None:  # noqa: ANN001
    agent_state = _state(tmp_path, mode="agent")
    assert maybe_escalate_to_agent(agent_state, "幫我寫一支爬蟲") is False
    chat_state = _state(tmp_path, mode="chat")
    assert maybe_escalate_to_agent(chat_state, "什麼是 agentX") is False
    assert chat_state.mode == "chat"
