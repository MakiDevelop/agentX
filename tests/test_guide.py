from unittest.mock import MagicMock, patch

from agentx.cli import (
    GUIDE_MODE_ROWS,
    GUIDE_WORKFLOW_ROWS,
    SLASH_COMMANDS,
    WORKFLOW_ROWS,
    ShellState,
    format_workflow_recipe,
    print_guide,
    workflow_recipe,
)


def test_guide_command_is_registered() -> None:
    commands = dict(SLASH_COMMANDS)

    assert "/guide" in commands
    assert "/workflows" in commands
    assert "/workflow NAME" in commands
    assert "快速導覽" in commands["/guide"]


def test_guide_covers_three_modes_and_core_workflows() -> None:
    modes = {row[0] for row in GUIDE_MODE_ROWS}
    workflows = "\n".join(row[1] for row in GUIDE_WORKFLOW_ROWS)

    assert modes == {"chat", "ask", "shell"}
    assert "/files" in workflows
    assert "/test" in workflows
    assert "/resume latest" in workflows
    workflow_rows = "\n".join(row[1] for row in WORKFLOW_ROWS)
    assert "/mode ask" in workflow_rows
    assert "--artifact-dir" in workflow_rows
    assert "handoff-resume" in workflow_rows
    assert "/transcript approvals latest --denied" in workflow_rows


def test_workflow_recipe_resolves_aliases() -> None:
    assert workflow_recipe("headless") == (
        "Headless bundle",
        'agentx -p "任務" --agent --artifact-dir .agentx/runs/latest --quiet  →  agentx handoff-resume .agentx/runs/latest --dry-run',
    )
    assert workflow_recipe("audit") == (
        "Approval audit",
        "/sessions  →  /transcript approvals latest --denied  →  /transcript approvals SESSION",
    )


def test_format_workflow_recipe_reports_missing_name() -> None:
    output = format_workflow_recipe("missing")

    assert "workflow not found: missing" in output
    assert "headless" in output


def test_mode_ask_alias_uses_agent_mode(tmp_path) -> None:
    state = ShellState(settings=MagicMock(workspace=tmp_path))

    state.set_chat_mode("ask")

    assert state.mode == "agent"


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
