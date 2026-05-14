from agentx.safety import Risk, classify_command, classify_tool


def test_read_only_tools_are_green() -> None:
    assert classify_tool("read_file") == Risk.GREEN
    assert classify_tool("git_diff") == Risk.GREEN


def test_memory_write_is_yellow() -> None:
    assert classify_tool("memory_write") == Risk.YELLOW


def test_unknown_tool_is_red() -> None:
    assert classify_tool("run_command") == Risk.RED


def test_destructive_commands_are_red() -> None:
    assert classify_command("rm -rf /tmp/demo") == Risk.RED
    assert classify_command("rsync --delete a b") == Risk.RED
    assert classify_command("chmod -R 777 .") == Risk.RED

