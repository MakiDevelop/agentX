from pathlib import Path

from helpers import make_settings
from test_cli_runtime_handlers import FakeTranscript, _capture, _state

from agentx.bootstrap import build_local_instruction_context, build_repo_context
from agentx.chat_turn import ChatTurn, NativeToolCall
from agentx.cli_runtime_handlers import handle_mode
from agentx.config import DEFAULT_MAX_STEPS, DEFAULT_MODE, Settings
from agentx.loop import AgentSession
from agentx.model_size import is_small_local_model
from agentx.persona import persona_prompt
from agentx.runtime_prompt import build_agent_system_prompt
from agentx.tools import ToolRegistry, builtin_tools


class _NativeOllama:
    model = "gemma4:31b"

    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict] = []
        self.last_prompt_tokens = 0

    def chat_turn(self, messages, *, tools=None, cancel_event=None, json_mode=False):  # noqa: ANN001
        self.calls.append({"tools": tools, "json_mode": json_mode, "n_messages": len(messages)})
        return self.turns.pop(0)


class _Memory:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        self.queries.append(query)
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"


def test_gemma4_31b_is_not_a_small_model() -> None:
    assert is_small_local_model("gemma4:31b") is False
    assert is_small_local_model("qwen3.6:32b") is False
    assert is_small_local_model("gemma2:2b") is True
    assert is_small_local_model("llama3.2:3b") is True


def test_gemma4_31b_does_not_get_weak_persona_or_ritual() -> None:
    prompt = build_agent_system_prompt(model="gemma4:31b")
    assert "Compensation Layer" not in prompt
    assert "女子大學生" not in persona_prompt("default", "gemma4:31b")
    assert "弱本地模型" not in persona_prompt("default", "gemma4:31b")
    assert "Do not stop until the user's request is actually done" in prompt


def test_small_model_still_gets_compensation() -> None:
    prompt = build_agent_system_prompt(model="gemma2:2b")
    assert "Compensation Layer" in prompt


def test_defaults_are_agent_mode_and_long_horizon(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("AGENTX_MAX_STEPS", raising=False)
    monkeypatch.delenv("AGENTX_LEARNING", raising=False)
    settings = Settings(workspace=tmp_path)
    assert settings.max_steps == DEFAULT_MAX_STEPS
    assert settings.max_steps >= 32
    assert DEFAULT_MODE == "agent"
    assert settings.learning_enabled is False
    assert settings.ollama_timeout >= 120


def test_native_tool_call_drives_the_real_ask_loop(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    ollama = _NativeOllama(
        [
            ChatTurn(tool_calls=(NativeToolCall("read_file", {"path": "hello.txt"}),)),
            ChatTurn(content='{"type":"final","content":"讀到 hi"}'),
        ]
    )
    memory = _Memory()
    session = AgentSession(
        settings=make_settings(tmp_path, model="gemma4:31b", max_steps=6, learning_enabled=False),
        ollama=ollama,  # type: ignore[arg-type]
        tools=ToolRegistry(builtin_tools(tmp_path, memory), auto_approve_yellow=True),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )
    answer = session.ask("讀一下 hello.txt")
    assert "hi" in answer or "讀到" in answer
    assert session.tool_call_count == 1
    assert ollama.calls[0]["tools"]
    assert any(
        (m.get("role") == "assistant" and m.get("tool_calls")) for m in session.messages
    )


def test_write_task_cannot_final_before_mutation(tmp_path: Path) -> None:
    ollama = _NativeOllama(
        [
            ChatTurn(content='{"type":"final","content":"爬蟲寫好了"}'),
            ChatTurn(
                tool_calls=(
                    NativeToolCall(
                        "write_file",
                        {"path": "erika_crawler.py", "content": "print(1)\n"},
                    ),
                )
            ),
            ChatTurn(content='{"type":"final","content":"已寫入 erika_crawler.py"}'),
        ]
    )
    memory = _Memory()
    session = AgentSession(
        settings=make_settings(tmp_path, model="gemma4:31b", max_steps=6, learning_enabled=False),
        ollama=ollama,  # type: ignore[arg-type]
        tools=ToolRegistry(builtin_tools(tmp_path, memory), auto_approve_yellow=True),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )
    answer = session.ask("幫我寫一支專門爬取 https://erika.chibakuma.com/ 的爬蟲")
    assert (tmp_path / "erika_crawler.py").is_file()
    assert "erika_crawler.py" in answer
    assert session.tool_call_count >= 1


def test_long_agentx_constitution_is_truncated(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text(
        "agentX 專案 Hard Mode 指引\n撞牆偵測\n" + ("x" * 4000),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    context = build_repo_context(tmp_path)
    local = build_local_instruction_context(tmp_path)
    assert "Hard Mode" in local
    assert local.count("x") < 600
    assert "read_file path=AGENTX.md" in local
    assert "Runtime card" in context
    assert len(context) < 8000 or context.startswith("Workspace:")


def test_ask_searches_memory_with_the_actual_task(tmp_path: Path) -> None:
    ollama = _NativeOllama([ChatTurn(content='{"type":"final","content":"ok"}')])
    memory = _Memory()
    session = AgentSession(
        settings=make_settings(tmp_path, model="gemma4:31b", max_steps=3, learning_enabled=False),
        ollama=ollama,  # type: ignore[arg-type]
        tools=ToolRegistry(builtin_tools(tmp_path, memory), auto_approve_yellow=True),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )
    session.ask("上次 erika.chibakuma.com 爬蟲做到哪")
    assert any("erika.chibakuma.com" in query for query in memory.queries)


def test_mode_switch_carries_chat_history(tmp_path: Path) -> None:
    state = _state(tmp_path, mode="chat")
    chat_messages = [
        {"role": "system", "content": "chat system"},
        {"role": "user", "content": "我想請你寫一支專門爬取 https://erika.chibakuma.com/ 的爬蟲"},
        {"role": "assistant", "content": "請先切換 agent 模式"},
    ]
    lines, emit = _capture()
    handle_mode(
        state,
        "/mode agent",
        transcript=FakeTranscript(),
        emit=emit,
        emit_error=lambda _msg: None,
        chat_messages=chat_messages,
    )
    assert state.mode == "agent"
    carried = " ".join(m.get("content", "") for m in state.agent_session.messages)
    assert "erika.chibakuma.com" in carried
    assert "tools were unavailable" in carried
    assert lines == ["mode=agent"]
