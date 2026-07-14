from typer.testing import CliRunner

from agentx import cli


def test_headless_exit_code_success() -> None:
    assert cli.headless_exit_code("完成") == 0


def test_headless_exit_code_task_failure() -> None:
    assert cli.headless_exit_code("任務失敗：工具 read_file 仍有未解決的錯誤") == 1
    assert cli.headless_exit_code("工具執行失敗：not found") == 1


def test_headless_exit_code_agent_control_failure() -> None:
    assert cli.headless_exit_code("模型沒有輸出有效的工具呼叫 JSON，已停止。") == 2
    assert cli.headless_exit_code("") == 2


def test_headless_exit_code_cancelled() -> None:
    assert cli.headless_exit_code("Ollama request cancelled") == 130


def test_print_prompt_uses_headless_exit_code(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "任務失敗：工具失敗")

    result = runner.invoke(cli.app, ["-p", "demo", "--agent"])

    assert result.exit_code == 1
    assert "任務失敗" in result.output


def test_print_prompt_success_exit_zero(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "完成")

    result = runner.invoke(cli.app, ["-p", "demo"])

    assert result.exit_code == 0
    assert "完成" in result.output
