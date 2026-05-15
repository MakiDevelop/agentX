from agentx.tui import format_assistant_header, format_user_message


def test_format_user_message_is_visually_separated() -> None:
    output = format_user_message("你好")

    assert "Maki" in output
    assert "你好" in output
    assert output.startswith("\n---")
    assert output.endswith("\n")


def test_format_assistant_header_is_visually_separated() -> None:
    output = format_assistant_header()

    assert "agentX" in output
    assert output.startswith("\n---")
    assert output.endswith("\n")
