from unittest.mock import MagicMock, patch

from agentx.cli import (
    COMMAND_CATALOG,
    COMMAND_EXAMPLES,
    COMMAND_RELATED,
    COMMAND_RISK_HINTS,
    GUIDE_MODE_ROWS,
    GUIDE_WORKFLOW_ROWS,
    SLASH_COMMANDS,
    WORKFLOW_ROWS,
    ShellState,
    format_unknown_slash_command,
    format_workflow_recipe,
    print_guide,
    slash_command_help,
    slash_command_suggestions,
    workflow_recipe,
)


def test_guide_command_is_registered() -> None:
    commands = dict(SLASH_COMMANDS)

    command_keys = {command.split()[0]: desc for command, desc in SLASH_COMMANDS}

    assert "/help" in command_keys
    assert "/guide" in commands
    assert "/workflows" in commands
    assert "/workflow NAME" in commands
    assert "單一命令" in command_keys["/help"]
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


def test_slash_command_help_formats_single_command() -> None:
    output = slash_command_help("workflow")

    assert "Command: /workflow" in output
    assert "Usage: /workflow NAME" in output
    assert "Examples:" in output
    assert "/workflow headless" in output
    assert "Risk:" in output
    assert "Related:" in output


def test_all_slash_commands_have_help_metadata() -> None:
    commands = {command.split()[0] for command, _ in SLASH_COMMANDS}
    missing_examples = sorted(commands - set(COMMAND_EXAMPLES))
    missing_related = sorted(commands - set(COMMAND_RELATED))

    assert missing_examples == []
    assert missing_related == []
    for command in commands:
        assert COMMAND_EXAMPLES[command]
        assert COMMAND_RELATED[command]
        assert any(example.startswith(command) for example in COMMAND_EXAMPLES[command])


def test_command_catalog_generates_help_surfaces() -> None:
    usages = [str(item["usage"]) for item in COMMAND_CATALOG]
    catalog_keys = [str(item["usage"]).split()[0] for item in COMMAND_CATALOG]

    assert len(usages) == len(set(usages))
    assert SLASH_COMMANDS == [
        (str(item["usage"]), str(item["description"]))
        for item in COMMAND_CATALOG
    ]
    assert set(COMMAND_EXAMPLES) == set(catalog_keys)
    assert set(COMMAND_RELATED) == set(catalog_keys)
    for item in COMMAND_CATALOG:
        key = str(item["usage"]).split()[0]
        assert key in COMMAND_EXAMPLES
        assert key in COMMAND_RELATED
        if "risk" in item:
            assert COMMAND_RISK_HINTS[key] == item["risk"]


def test_slash_command_help_reports_unknown_command() -> None:
    output = slash_command_help("missing")

    assert "command not found: missing" in output
    assert "/workflow" in output


def test_slash_command_suggestions_find_typo() -> None:
    assert "/workflow" in slash_command_suggestions("/wrkflow")
    assert "/transcript" in slash_command_suggestions("trancript")


def test_format_unknown_slash_command_includes_suggestions() -> None:
    output = format_unknown_slash_command("/wrkflow headless")

    assert "unknown slash command: /wrkflow" in output
    assert "Did you mean:" in output
    assert "/workflow" in output
    assert "/help COMMAND" in output


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
