from test_cli_runtime_handlers import _state

from agentx.cli_runtime_handlers import maybe_escalate_to_agent, maybe_run_orchestrator
from agentx.intent_route import should_auto_orchestrate, should_orchestrate, should_use_agent


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


def test_should_orchestrate_skips_single_file_tasks() -> None:
    assert should_orchestrate("幫我寫一支專門爬取 https://erika.chibakuma.com/ 的爬蟲") is False
    assert should_orchestrate("Write a file named hello_agentx.txt") is False
    assert should_orchestrate("讀一下 README.md") is False
    assert should_orchestrate("demo") is False


def test_should_orchestrate_complex_or_explicit_work() -> None:
    assert should_orchestrate("拆成子任務：先讀 loop，再拆 compact，最後補測試")
    assert should_orchestrate(
        "幫我重構 src/agentx/loop.py 與 src/agentx/bootstrap.py，遷移架構並補測試"
    )
    numbered = "請依序做：\n1. 改 API\n2. 改 CLI\n3. 補測試\n"
    assert should_orchestrate(numbered)


def test_should_auto_orchestrate_respects_gates(monkeypatch) -> None:  # noqa: ANN001
    complex_prompt = "拆成子任務：先讀 loop，再拆 compact，最後補測試"
    assert should_auto_orchestrate(complex_prompt, agent_mode=True) is True
    assert should_auto_orchestrate(complex_prompt, agent_mode=False) is False
    assert should_auto_orchestrate(complex_prompt, agent_mode=True, plan_mode=True) is False
    assert should_auto_orchestrate(complex_prompt, agent_mode=True, resume=True) is False
    assert should_auto_orchestrate("demo", agent_mode=True, force=True) is True
    monkeypatch.setenv("AGENTX_AUTO_ORCHESTRATE", "0")
    assert should_auto_orchestrate(complex_prompt, agent_mode=True) is False


def test_maybe_run_orchestrator_only_for_complex_agent_tasks(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    state = _state(tmp_path, mode="agent")
    seen: list[str] = []

    class FakeOrch:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            pass

        def run(self, prompt: str, namespace: str = "") -> object:
            seen.append(prompt)
            return type("R", (), {"summary": "orch-done"})()

    monkeypatch.setattr("agentx.orchestrator.Orchestrator", FakeOrch)
    assert (
        maybe_run_orchestrator(
            state, "讀一下 README.md", ollama=None, memory=None, tools=None, namespace="t"
        )
        is None
    )
    assert seen == []
    answer = maybe_run_orchestrator(
        state,
        "拆成子任務：先讀 loop，再拆 compact，最後補測試",
        ollama=None,
        memory=None,
        tools=None,
        namespace="t",
    )
    assert answer == "orch-done"
    assert seen
    carried = " ".join(m.get("content", "") for m in state.agent_session.messages)
    assert "Orchestrator finished" in carried
