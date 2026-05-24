from unittest.mock import patch

from agentx.cli import GUIDE_MODE_ROWS, GUIDE_WORKFLOW_ROWS, SLASH_COMMANDS, print_guide


def test_guide_command_is_registered() -> None:
    commands = dict(SLASH_COMMANDS)

    assert "/guide" in commands
    assert "快速導覽" in commands["/guide"]


def test_guide_covers_three_modes_and_core_workflows() -> None:
    modes = {row[0] for row in GUIDE_MODE_ROWS}
    workflows = "\n".join(row[1] for row in GUIDE_WORKFLOW_ROWS)

    assert modes == {"chat", "ask", "shell"}
    assert "/files" in workflows
    assert "/test" in workflows
    assert "/resume latest" in workflows


def test_print_guide_renders_orientation() -> None:
    with patch("agentx.cli.console") as fake_console:
        print_guide()

    printed = [call.args[0] for call in fake_console.print.call_args_list if call.args]
    rendered = "\n".join(
        str(getattr(item, "renderable", item))
        for item in printed
    )

    assert "agentX 60 秒導覽" in rendered
    assert "下一步" in rendered
