from agentx.doctor import _check_command


def test_check_command_reports_success() -> None:
    name, ok, detail = _check_command("python", ["python", "--version"])

    assert name == "python"
    assert ok
    assert "Python" in detail
