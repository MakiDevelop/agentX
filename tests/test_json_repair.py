from agentx.json_repair import extract_json_object


def test_extracts_plain_json() -> None:
    assert extract_json_object('{"type":"final","content":"ok"}') == {
        "type": "final",
        "content": "ok",
    }


def test_extracts_json_code_block() -> None:
    raw = 'Here:\n```json\n{"type":"tool_call","tool":"git_status","args":{}}\n```'
    assert extract_json_object(raw) == {"type": "tool_call", "tool": "git_status", "args": {}}


def test_extracts_balanced_json_with_prefix_suffix() -> None:
    raw = '好的 {"type":"tool_call","tool":"list_files","args":{"path":"."}} 謝謝'
    assert extract_json_object(raw) == {
        "type": "tool_call",
        "tool": "list_files",
        "args": {"path": "."},
    }


def test_returns_none_without_json_object() -> None:
    assert extract_json_object("我無法執行工具") is None
