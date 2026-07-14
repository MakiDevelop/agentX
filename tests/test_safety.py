from agentx.safety import Risk, classify_command, classify_tool


def test_read_only_tools_are_green() -> None:
    assert classify_tool("read_file") == Risk.GREEN
    assert classify_tool("git_diff") == Risk.GREEN
    assert classify_tool("locate_topic") == Risk.GREEN


def test_memory_write_is_yellow() -> None:
    assert classify_tool("memory_write") == Risk.YELLOW


def test_git_push_tool_is_yellow_but_force_push_command_is_red() -> None:
    assert classify_tool("git_push") == Risk.YELLOW
    assert classify_command("git push --force") == Risk.RED
    assert classify_command("git push -f") == Risk.RED


def test_run_command_is_green_but_allowlisted_in_tool_layer() -> None:
    assert classify_tool("run_command") == Risk.GREEN


def test_destructive_commands_are_red() -> None:
    assert classify_command("rm -rf /tmp/demo") == Risk.RED
    assert classify_command("rsync --delete a b") == Risk.RED
    assert classify_command("chmod -R 777 .") == Risk.RED


def test_sensitive_paths_are_red() -> None:
    assert classify_command("cat ~/.ssh/config") == Risk.RED
    assert classify_command("cat /Users/maki/.gnupg/pubring.kbx") == Risk.RED
    assert classify_command("ls .secrets") == Risk.RED


def test_absolute_multi_path_mv_is_red() -> None:
    assert classify_command("mv /Volumes/A/file /Volumes/B/file") == Risk.RED
