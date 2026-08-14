from agentx.chat_turn import ChatTurn
from agentx.ollama import OllamaClient, _parse_tool_calls, _turn_from_message


def test_parse_tool_calls_from_ollama_message() -> None:
    calls = _parse_tool_calls(
        [
            {
                "function": {
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                }
            }
        ]
    )
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "README.md"}


def test_parse_tool_calls_accepts_json_string_arguments() -> None:
    calls = _parse_tool_calls(
        [{"function": {"name": "write_file", "arguments": '{"path":"a.py","content":"x"}'}}]
    )
    assert calls[0].arguments == {"path": "a.py", "content": "x"}


def test_turn_from_message_keeps_content_and_calls() -> None:
    turn = _turn_from_message(
        {
            "content": "",
            "tool_calls": [{"function": {"name": "list_files", "arguments": {"path": "."}}}],
        }
    )
    assert turn.content == ""
    assert turn.has_tool_calls
    assert turn.tool_calls[0].name == "list_files"


def test_chat_does_not_set_json_mode_when_tools_are_present(monkeypatch) -> None:  # noqa: ANN001
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "list_files", "arguments": {"path": "."}}}
                    ],
                },
                "prompt_eval_count": 12,
            }

    class _Http:
        def post(self, url: str, json: dict) -> _Resp:  # noqa: A003
            captured["url"] = url
            captured["payload"] = json
            return _Resp()

    client = OllamaClient("http://127.0.0.1:11434", "gemma4:31b")
    client._client = _Http()  # type: ignore[assignment]
    turn = client.chat_turn(
        [{"role": "user", "content": "list files"}],
        json_mode=True,
        tools=[{"type": "function", "function": {"name": "list_files"}}],
    )
    assert "format" not in captured["payload"]
    assert captured["payload"]["tools"]
    assert isinstance(turn, ChatTurn)
    assert turn.tool_calls[0].name == "list_files"
    assert client.last_prompt_tokens == 12


def test_chat_still_returns_content_string() -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": "hello"}}

    class _Http:
        def post(self, url: str, json: dict) -> _Resp:  # noqa: A003
            return _Resp()

    client = OllamaClient("http://127.0.0.1:11434", "gemma4:31b")
    client._client = _Http()  # type: ignore[assignment]
    assert client.chat([{"role": "user", "content": "hi"}]) == "hello"
