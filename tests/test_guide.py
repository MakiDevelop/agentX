from agentx.cli import GUIDE_MODE_ROWS, GUIDE_WORKFLOW_ROWS, SLASH_COMMANDS


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
