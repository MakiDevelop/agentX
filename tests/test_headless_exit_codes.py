import json
from types import SimpleNamespace

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


def test_structured_headless_exit_code_overrides_success_text() -> None:
    assert cli.headless_exit_code("看起來完成", termination="final_failed", failing_tools=("run_tests",)) == 1
    assert cli.headless_exit_code("完成", termination="max_steps_exceeded") == 2
    assert cli.headless_exit_code("完成", termination="cancelled") == 130


def test_structured_headless_exit_code_clean_final_success() -> None:
    assert cli.headless_exit_code("任務失敗這幾個字只是被引用", termination="final_success") == 0
    assert cli.headless_exit_code("done", termination="direct_tool_success") == 0
    assert cli.headless_exit_code("done", termination="direct_tool_failure") == 1


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


def test_print_prompt_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(
            output="文字看似完成",
            termination="final_failed",
            failing_tools=("run_tests",),
        ),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent"])

    assert result.exit_code == 1
    assert "文字看似完成" in result.output


def test_headless_json_payload_includes_stats() -> None:
    payload = cli.headless_json_payload(
        cli.HeadlessRunResult(
            output="完成",
            termination="final_success",
            stats={"message_count": 3, "error_count": 0},
        ),
        exit_code=0,
    )

    data = json.loads(payload)

    assert data["output"] == "完成"
    assert data["exit_code"] == 0
    assert data["termination"] == "final_success"
    assert data["failing_tools"] == []
    assert data["stats"]["message_count"] == 3


def test_headless_run_stats_summarizes_session_state() -> None:
    session = SimpleNamespace(
        message_count=9,
        context_tokens_estimate=1234,
        error_history=[object(), object()],
        compaction_count=1,
        pending_verifies={"src/a.py"},
        tasks=[
            {"status": "pending"},
            {"status": "in_progress"},
            {"status": "done"},
            {"status": "blocked"},
            {"status": "unknown"},
        ],
    )

    stats = cli.headless_run_stats(session)  # type: ignore[arg-type]

    assert stats["message_count"] == 9
    assert stats["context_tokens_estimate"] == 1234
    assert stats["error_count"] == 2
    assert stats["compaction_count"] == 1
    assert stats["pending_verifies"] == ["src/a.py"]
    assert stats["task_counts"] == {
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "blocked": 1,
    }


def test_print_prompt_json_output_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(
            output="文字看似完成",
            termination="final_failed",
            failing_tools=("run_tests",),
            stats={"message_count": 7, "error_count": 1},
        ),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 1
    assert data["output"] == "文字看似完成"
    assert data["exit_code"] == 1
    assert data["termination"] == "final_failed"
    assert data["failing_tools"] == ["run_tests"]
    assert data["stats"]["error_count"] == 1
