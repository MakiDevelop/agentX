from agentx.cli import SLASH_COMMANDS, format_plan_status


def test_format_plan_status_on() -> None:
    assert "on" in format_plan_status(True)
    assert "只討論方案" in format_plan_status(True)


def test_format_plan_status_off() -> None:
    assert format_plan_status(False) == "off"


def test_plan_command_is_registered() -> None:
    commands = [cmd for cmd, _ in SLASH_COMMANDS]
    assert "/plan" in commands

    desc = dict(SLASH_COMMANDS)["/plan"]
    assert "plan 模式" in desc
    assert "只討論方案" in desc
