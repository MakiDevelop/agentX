import json
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agentx import cli
from agentx.errors import ErrorContext, ErrorType
from agentx.session_store import SessionStore


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
    assert cli.headless_exit_code("runtime error: timeout", termination="runtime_error") == 2
    assert cli.headless_exit_code("run timed out", termination="timeout") == 124
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
            log_summary={"tool_outcomes": {"run_tests": True}},
        ),
        exit_code=0,
    )

    data = json.loads(payload)

    assert data["schema_version"] == cli.HEADLESS_PAYLOAD_SCHEMA_VERSION
    assert data["output"] == "完成"
    assert data["exit_code"] == 0
    assert data["termination"] == "final_success"
    assert data["failing_tools"] == []
    assert data["stats"]["message_count"] == 3
    assert data["log_summary"]["tool_outcomes"] == {"run_tests": True}
    assert data["session_path"] is None
    assert "phases" not in data


def test_headless_payload_enriches_handoff_with_resume_command() -> None:
    payload = cli.headless_payload(
        cli.HeadlessRunResult(
            output="stopped",
            termination="max_steps_exceeded",
            log_summary={
                "handoff_summary": {
                    "status": "max_steps_exceeded",
                    "needs_handoff": True,
                    "next_steps": [],
                }
            },
            session_path="/repo/.agentx/sessions/20260715-123456.session.jsonl",
        ),
        exit_code=2,
    )

    handoff = payload["log_summary"]["handoff_summary"]

    assert handoff["session_path"] == "/repo/.agentx/sessions/20260715-123456.session.jsonl"
    assert handoff["resume_session"] == "20260715-123456.session.jsonl"
    assert (
        handoff["resume_command"]
        == "agentx -p '<next prompt>' --agent --resume-session 20260715-123456.session.jsonl --json"
    )
    assert "Resume with the provided resume_command." in handoff["next_steps"]


def test_headless_payload_contract_required_keys() -> None:
    payload = cli.headless_payload(
        cli.HeadlessRunResult(
            output="stopped",
            termination="final_failed",
            failing_tools=("run_tests",),
            stats={"message_count": 3, "task_counts": {"in_progress": 1}},
            log_summary={
                "termination": "final_failed",
                "tool_outcomes": {"run_tests": False, "read_file": True},
                "successful_tools": ["read_file"],
                "failing_tools": ["run_tests"],
                "recent_errors": [
                    {
                        "type": "execution_error",
                        "tool": "run_tests",
                        "message": "pytest failed",
                        "attempt_count": 1,
                    }
                ],
                "recovery_suggestions": [
                    {
                        "action": "verify_assumption",
                        "confidence": 0.75,
                        "description": "read files",
                        "rationale": "state stale",
                    }
                ],
                "pending_verifies": ["src/a.py"],
                "handoff_summary": cli.headless_handoff_summary(
                    termination="final_failed",
                    failing_tools=["run_tests"],
                    recent_errors=[
                        {
                            "type": "execution_error",
                            "tool": "run_tests",
                            "message": "pytest failed",
                            "attempt_count": 1,
                        }
                    ],
                    recovery_suggestions=[
                        {
                            "action": "verify_assumption",
                            "confidence": 0.75,
                            "description": "read files",
                            "rationale": "state stale",
                        }
                    ],
                    pending_verifies=["src/a.py"],
                    stats={"task_counts": {"in_progress": 1}},
                ),
            },
            session_path="/repo/.agentx/sessions/contract.session.jsonl",
        ),
        exit_code=1,
    )

    assert {
        "schema_version",
        "output",
        "exit_code",
        "termination",
        "failing_tools",
        "stats",
        "log_summary",
        "session_path",
    }.issubset(payload)
    assert payload["schema_version"] == cli.HEADLESS_PAYLOAD_SCHEMA_VERSION

    log_summary = payload["log_summary"]
    assert {
        "termination",
        "tool_outcomes",
        "successful_tools",
        "failing_tools",
        "recent_errors",
        "recovery_suggestions",
        "pending_verifies",
        "handoff_summary",
    }.issubset(log_summary)

    handoff = log_summary["handoff_summary"]
    assert {
        "status",
        "needs_handoff",
        "failing_tools",
        "pending_verifies",
        "task_counts",
        "last_error",
        "recovery_actions",
        "primary_recovery",
        "recovery_checklist",
        "next_steps",
        "session_path",
        "resume_session",
        "resume_command",
    }.issubset(handoff)
    assert handoff["resume_session"] == "contract.session.jsonl"
    assert handoff["resume_command"].endswith("--resume-session contract.session.jsonl --json")


def test_headless_payload_contract_fixture_supports_runner_takeover() -> None:
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))

    assert event["event"] == "result"
    payload = event["data"]
    handoff = payload["log_summary"]["handoff_summary"]

    assert payload["exit_code"] == 1
    assert payload["termination"] == "final_failed"
    assert handoff["needs_handoff"] is True
    assert handoff["resume_command"] == (
        "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json"
    )
    assert handoff["recovery_actions"] == ["verify_assumption"]
    assert handoff["recovery_checklist"][-1] == (
        "Run the smallest targeted verification that can prove or disprove the assumption."
    )


def test_handoff_inspect_payload_extracts_takeover_fields() -> None:
    fixture = Path("tests/fixtures/headless_result_failure.json")
    payload = cli.load_headless_payload_file(fixture)
    inspected = cli.inspect_headless_handoff_payload(payload)

    assert inspected["schema_version"] == cli.HEADLESS_PAYLOAD_SCHEMA_VERSION
    assert inspected["status"] == "final_failed"
    assert inspected["needs_handoff"] is True
    assert inspected["resume_session"] == "contract.session.jsonl"
    assert inspected["resume_command"] == (
        "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json"
    )
    assert inspected["recovery_actions"] == ["verify_assumption"]
    assert inspected["recovery_checklist"][-1] == (
        "Run the smallest targeted verification that can prove or disprove the assumption."
    )


def test_handoff_inspect_command_plain_output() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["handoff-inspect", "tests/fixtures/headless_result_failure.json"])

    assert result.exit_code == 0
    assert "schema_version: agentx.headless_result.v1" in result.output
    assert "status: final_failed" in result.output
    assert "resume_command: agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json" in result.output
    assert "- Run the smallest targeted verification" in result.output


def test_handoff_inspect_command_jsonl_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["handoff-inspect", "tests/fixtures/headless_result_failure.json", "--output-format", "jsonl"],
    )
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["event"] == "handoff_inspect"
    assert event["data"]["resume_session"] == "contract.session.jsonl"
    assert event["data"]["recovery_actions"] == ["verify_assumption"]


def test_handoff_inspect_field_resume_command_plain() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["handoff-inspect", "tests/fixtures/headless_result_failure.json", "--field", "resume_command"],
    )

    assert result.exit_code == 0
    assert result.output == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json\n"


def test_handoff_inspect_default_exit_zero_for_failed_payload() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["handoff-inspect", "tests/fixtures/headless_result_failure.json", "--field", "resume_command"],
    )

    assert result.exit_code == 0
    assert result.output == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json\n"


def test_handoff_inspect_use_payload_exit_code_plain() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--use-payload-exit-code",
        ],
    )

    assert result.exit_code == 1
    assert result.output == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json\n"


def test_handoff_inspect_use_payload_exit_code_jsonl() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--output-format",
            "jsonl",
            "--use-payload-exit-code",
        ],
    )
    event = json.loads(result.output)

    assert result.exit_code == 1
    assert event["event"] == "handoff_inspect_field"
    assert event["data"]["value"] == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json"


def test_handoff_inspect_require_handoff_accepts_ready_payload() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--require-handoff",
        ],
    )

    assert result.exit_code == 0
    assert result.output == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json\n"


def test_handoff_inspect_require_handoff_rejects_missing_resume_command(tmp_path: Path) -> None:
    runner = CliRunner()
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    event["data"]["log_summary"]["handoff_summary"]["resume_command"] = None
    event["data"]["log_summary"]["handoff_summary"]["resume_session"] = None
    target = tmp_path / "result.json"
    target.write_text(json.dumps(event), encoding="utf-8")

    result = runner.invoke(cli.app, ["handoff-inspect", str(target), "--field", "resume_command", "--require-handoff"])

    assert result.exit_code == 1
    assert result.output == "\n"


def test_handoff_inspect_require_handoff_jsonl_still_prints_payload(tmp_path: Path) -> None:
    runner = CliRunner()
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    event["data"]["log_summary"]["handoff_summary"]["needs_handoff"] = False
    target = tmp_path / "result.json"
    target.write_text(json.dumps(event), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["handoff-inspect", str(target), "--output-format", "jsonl", "--require-handoff"],
    )
    output_event = json.loads(result.output)

    assert result.exit_code == 1
    assert output_event["event"] == "handoff_inspect"
    assert output_event["data"]["needs_handoff"] is False
    assert output_event["data"]["resume_command"] == (
        "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json"
    )


def test_handoff_inspect_require_handoff_ready_can_preserve_payload_exit_code() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--require-handoff",
            "--use-payload-exit-code",
        ],
    )

    assert result.exit_code == 1
    assert result.output == "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json\n"


def test_handoff_inspect_require_schema_version_accepts_current_fixture() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "schema_version",
            "--require-schema-version",
        ],
    )

    assert result.exit_code == 0
    assert result.output == f"{cli.HEADLESS_PAYLOAD_SCHEMA_VERSION}\n"


def test_handoff_inspect_require_schema_version_rejects_missing_schema(tmp_path: Path) -> None:
    runner = CliRunner()
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    event["data"].pop("schema_version")
    target = tmp_path / "legacy-result.json"
    target.write_text(json.dumps(event), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["handoff-inspect", str(target), "--field", "schema_version", "--require-schema-version"],
    )

    assert result.exit_code == 1
    assert result.output == "\n"


def test_handoff_inspect_require_schema_version_jsonl_still_prints_payload(tmp_path: Path) -> None:
    runner = CliRunner()
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    event["data"]["schema_version"] = "agentx.headless_result.v0"
    target = tmp_path / "old-result.json"
    target.write_text(json.dumps(event), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["handoff-inspect", str(target), "--output-format", "jsonl", "--require-schema-version"],
    )
    output_event = json.loads(result.output)

    assert result.exit_code == 1
    assert output_event["event"] == "handoff_inspect"
    assert output_event["data"]["schema_version"] == "agentx.headless_result.v0"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"exit_code": 0}, 0),
        ({"exit_code": 124}, 124),
        ({"exit_code": 999}, 255),
        ({"exit_code": -3}, 0),
        ({"exit_code": True}, 1),
        ({"exit_code": False}, 0),
        ({"exit_code": "failed"}, 1),
        ({}, 1),
    ],
)
def test_handoff_inspect_exit_code_normalizes_payload_exit_code(
    payload: dict[str, object],
    expected: int,
) -> None:
    assert cli.handoff_inspect_exit_code(payload, use_payload_exit_code=True) == expected
    assert cli.handoff_inspect_exit_code(payload, use_payload_exit_code=False) == 0


def test_handoff_takeover_ready_requires_flag_and_resume_command() -> None:
    assert cli.handoff_takeover_ready({"needs_handoff": True, "resume_command": "agentx ..."}) is True
    assert cli.handoff_takeover_ready({"needs_handoff": False, "resume_command": "agentx ..."}) is False
    assert cli.handoff_takeover_ready({"needs_handoff": True, "resume_command": None}) is False


def test_handoff_schema_version_matches_current_contract() -> None:
    assert cli.handoff_schema_version_matches({"schema_version": cli.HEADLESS_PAYLOAD_SCHEMA_VERSION}) is True
    assert cli.handoff_schema_version_matches({"schema_version": "agentx.headless_result.v0"}) is False
    assert cli.handoff_schema_version_matches({}) is False


def test_handoff_inspect_next_prompt_updates_resume_command() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--next-prompt",
            "照上一輪繼續",
        ],
    )

    assert result.exit_code == 0
    assert result.output == (
        "agentx -p '照上一輪繼續' --agent --resume-session contract.session.jsonl --json\n"
    )


def test_handoff_inspect_next_prompt_quotes_shell_sensitive_text() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--next-prompt",
            "fix Bob's test",
        ],
    )

    assert result.exit_code == 0
    assert result.output == (
        'agentx -p \'fix Bob\'"\'"\'s test\' --agent --resume-session contract.session.jsonl --json\n'
    )


def test_handoff_inspect_field_recovery_checklist_plain() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["handoff-inspect", "tests/fixtures/headless_result_failure.json", "--field", "recovery_checklist"],
    )

    assert result.exit_code == 0
    assert "Inspect and verify pending edited paths before new edits.\n" in result.output
    assert result.output.rstrip().endswith(
        "Run the smallest targeted verification that can prove or disprove the assumption."
    )


def test_handoff_inspect_field_jsonl_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--output-format",
            "jsonl",
        ],
    )
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["event"] == "handoff_inspect_field"
    assert event["data"] == {
        "field": "resume_command",
        "value": "agentx -p '<next prompt>' --agent --resume-session contract.session.jsonl --json",
    }


def test_handoff_inspect_next_prompt_jsonl_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "tests/fixtures/headless_result_failure.json",
            "--field",
            "resume_command",
            "--next-prompt",
            "照上一輪繼續",
            "--output-format",
            "jsonl",
        ],
    )
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["data"]["value"] == (
        "agentx -p '照上一輪繼續' --agent --resume-session contract.session.jsonl --json"
    )


def test_handoff_inspect_field_rejects_unknown() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["handoff-inspect", "tests/fixtures/headless_result_failure.json", "--field", "missing"],
    )

    assert result.exit_code != 0
    assert "unknown handoff inspect field" in result.output


def test_handoff_inspect_reads_jsonl_input(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    target = tmp_path / "result.jsonl"
    target.write_text(
        "\n".join([
            json.dumps({"event": "dry_run", "data": {"ok": True}}),
            json.dumps(event),
        ]),
        encoding="utf-8",
    )

    payload = cli.load_headless_payload_file(target)
    inspected = cli.inspect_headless_handoff_payload(payload)

    assert inspected["status"] == "final_failed"
    assert inspected["resume_session"] == "contract.session.jsonl"


def test_handoff_inspect_reads_stdin_jsonl() -> None:
    runner = CliRunner()
    fixture = Path("tests/fixtures/headless_result_failure.json")
    event = json.loads(fixture.read_text(encoding="utf-8"))
    jsonl_input = "\n".join([
        json.dumps({"event": "dry_run", "data": {"ok": True}}),
        json.dumps(event),
    ])

    result = runner.invoke(
        cli.app,
        [
            "handoff-inspect",
            "-",
            "--field",
            "resume_command",
            "--next-prompt",
            "照上一輪繼續",
        ],
        input=jsonl_input,
    )

    assert result.exit_code == 0
    assert result.output == (
        "agentx -p '照上一輪繼續' --agent --resume-session contract.session.jsonl --json\n"
    )


def test_headless_payload_keeps_resume_fields_null_without_session_path() -> None:
    payload = cli.headless_payload(
        cli.HeadlessRunResult(
            output="stopped",
            termination="timeout",
            log_summary={"handoff_summary": {"status": "timeout", "needs_handoff": True}},
        ),
        exit_code=124,
    )

    handoff = payload["log_summary"]["handoff_summary"]

    assert handoff["session_path"] is None
    assert handoff["resume_session"] is None
    assert handoff["resume_command"] is None


def test_headless_json_payload_includes_optional_phases() -> None:
    payload = cli.headless_json_payload(
        cli.HeadlessRunResult(
            output="combined",
            termination="final_success",
            phases=(
                {"name": "plan", "output": "PLAN"},
                {"name": "execution", "output": "EXEC"},
            ),
        ),
        exit_code=0,
    )

    data = json.loads(payload)

    assert data["output"] == "combined"
    assert data["phases"] == [
        {"name": "plan", "output": "PLAN"},
        {"name": "execution", "output": "EXEC"},
    ]


def test_headless_exception_result_is_structured() -> None:
    result = cli.headless_exception_result(RuntimeError("boom"), session_path="/tmp/run.session.jsonl")
    payload = json.loads(cli.headless_json_payload(result, cli.headless_exit_code(result.output, termination=result.termination)))

    assert payload["termination"] == "runtime_error"
    assert payload["exit_code"] == 2
    assert payload["output"] == "runtime error: RuntimeError: boom"
    assert payload["session_path"] == "/tmp/run.session.jsonl"
    assert payload["log_summary"]["recent_errors"] == [
        {
            "type": "runtime_error",
            "tool": "",
            "message": "RuntimeError: boom",
            "attempt_count": 1,
        }
    ]
    assert payload["log_summary"]["handoff_summary"]["status"] == "runtime_error"
    assert payload["log_summary"]["handoff_summary"]["needs_handoff"] is True
    assert payload["log_summary"]["handoff_summary"]["last_error"]["message"] == "RuntimeError: boom"


def test_headless_timeout_result_is_structured() -> None:
    result = cli.headless_timeout_result(1.5, session_path="/tmp/run.session.jsonl")
    payload = json.loads(cli.headless_json_payload(result, cli.headless_exit_code(result.output, termination=result.termination)))

    assert payload["termination"] == "timeout"
    assert payload["exit_code"] == 124
    assert payload["output"] == "run timed out after 1.5s"
    assert payload["session_path"] == "/tmp/run.session.jsonl"
    assert payload["log_summary"]["recent_errors"] == [
        {
            "type": "timeout",
            "tool": "",
            "message": "run timed out after 1.5s",
            "attempt_count": 1,
        }
    ]
    assert payload["log_summary"]["handoff_summary"]["status"] == "timeout"
    assert payload["log_summary"]["handoff_summary"]["needs_handoff"] is True


def test_run_with_headless_timeout_returns_timeout_result() -> None:
    def slow_runner(cancel_event):  # noqa: ANN001
        time.sleep(1)
        return cli.HeadlessRunResult(output="late", termination="final_success")

    result = cli.run_with_headless_timeout(slow_runner, run_timeout=0.01)

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.termination == "timeout"


def test_run_with_headless_timeout_passes_cancel_event() -> None:
    seen: list[bool] = []

    def quick_runner(cancel_event):  # noqa: ANN001
        seen.append(cancel_event is not None)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    result = cli.run_with_headless_timeout(quick_runner, run_timeout=1)

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.output == "ok"
    assert seen == [True]


def test_wants_json_output_accepts_json_alias() -> None:
    assert cli.wants_json_output(False, "json") is True
    assert cli.wants_json_output(False, "jsonl") is True
    assert cli.wants_jsonl_output(False, "jsonl") is True
    assert cli.structured_output_format(True, "plain") == "json"
    assert cli.structured_output_format(True, "jsonl") == "jsonl"
    assert cli.wants_json_output(True, "plain") is True
    assert cli.wants_json_output(False, "plain") is False


def test_wants_json_output_rejects_unknown_format() -> None:
    try:
        cli.wants_json_output(False, "yaml")
    except Exception as exc:
        assert "plain, json, jsonl" in str(exc)
    else:
        raise AssertionError("unknown output format should fail")


def test_structured_payload_text_wraps_jsonl_event() -> None:
    data = json.loads(cli.structured_payload_text({"ok": True}, output_format="jsonl", event="result"))

    assert data == {"event": "result", "data": {"ok": True}}


def test_backend_list_payload_registers_and_lists_backends(monkeypatch) -> None:  # noqa: ANN001
    called: list[bool] = []

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: called.append(True))
    monkeypatch.setattr(cli, "list_registered_backends", lambda: ["llama_cpp", "ollama"])

    assert cli.backend_list_payload() == ["llama_cpp", "ollama"]
    assert called == [True]


def test_list_backends_option_plain(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["--list-backends"])

    assert result.exit_code == 0
    assert result.output == "llama_cpp\nollama\n"


def test_list_backends_option_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["--list-backends", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data == {"backends": ["llama_cpp", "ollama"]}


def test_list_backends_option_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["--list-backends", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event == {"event": "backends", "data": {"backends": ["llama_cpp", "ollama"]}}


def test_backends_command_plain(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["backends"])

    assert result.exit_code == 0
    assert result.output == "llama_cpp\nollama\n"


def test_backends_command_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["backends", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data == {"backends": ["llama_cpp", "ollama"]}


def test_backends_command_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "backend_list_payload", lambda: ["llama_cpp", "ollama"])

    result = runner.invoke(cli.app, ["backends", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event == {"event": "backends", "data": {"backends": ["llama_cpp", "ollama"]}}


def test_model_list_payload_uses_selected_backend_and_closes(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def list_models(self) -> list[str]:
            return ["a", "b"]

        def close(self) -> None:
            self.closed = True
            seen["closed"] = True

    fake_client = FakeClient()

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "base_url": base_url, "model": model, "timeout": timeout})
        return fake_client

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    payload = cli.model_list_payload(
        workspace_override=tmp_path,
        backend_override="llama_cpp",
        base_url_override="http://127.0.0.1:8081",
        model_override="local-model",
        timeout_override=12.0,
    )

    assert payload == {
        "backend": "llama_cpp",
        "base_url": "http://127.0.0.1:8081",
        "models": ["a", "b"],
    }
    assert seen == {
        "name": "llama_cpp",
        "base_url": "http://127.0.0.1:8081",
        "model": "local-model",
        "timeout": 12.0,
        "closed": True,
    }


def test_list_models_option_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "model_list_payload",
        lambda **kwargs: {"backend": "ollama", "base_url": "http://x", "models": ["a", "b"]},
    )

    result = runner.invoke(cli.app, ["--list-models", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data == {"backend": "ollama", "base_url": "http://x", "models": ["a", "b"]}


def test_list_models_option_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "model_list_payload",
        lambda **kwargs: {"backend": "ollama", "base_url": "http://x", "models": ["a", "b"]},
    )

    result = runner.invoke(cli.app, ["--list-models", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event == {
        "event": "models",
        "data": {"backend": "ollama", "base_url": "http://x", "models": ["a", "b"]},
    }


def test_models_command_plain(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "model_list_payload",
        lambda **kwargs: {"backend": "ollama", "base_url": "http://x", "models": ["a", "b"]},
    )

    result = runner.invoke(cli.app, ["models"])

    assert result.exit_code == 0
    assert result.output == "a\nb\n"


def test_version_payload_reads_package_version(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli, "package_version", lambda name: "9.8.7")

    payload = cli.version_payload()

    assert payload["agentx"] == "9.8.7"
    assert payload["python"]


def test_version_option_plain(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "version_payload", lambda: {"agentx": "9.8.7", "python": "3.13.0"})

    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output == "agentx 9.8.7\npython 3.13.0\n"


def test_version_option_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "version_payload", lambda: {"agentx": "9.8.7", "python": "3.13.0"})

    result = runner.invoke(cli.app, ["--version", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data == {"agentx": "9.8.7", "python": "3.13.0"}


def test_version_option_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "version_payload", lambda: {"agentx": "9.8.7", "python": "3.13.0"})

    result = runner.invoke(cli.app, ["--version", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event == {"event": "version", "data": {"agentx": "9.8.7", "python": "3.13.0"}}


def test_version_command_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "version_payload", lambda: {"agentx": "9.8.7", "python": "3.13.0"})

    result = runner.invoke(cli.app, ["version", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data == {"agentx": "9.8.7", "python": "3.13.0"}


def test_version_command_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "version_payload", lambda: {"agentx": "9.8.7", "python": "3.13.0"})

    result = runner.invoke(cli.app, ["version", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event == {"event": "version", "data": {"agentx": "9.8.7", "python": "3.13.0"}}


def test_load_headless_prompt_reads_workspace_file(tmp_path: Path) -> None:
    prompt = tmp_path / "briefing.md"
    prompt.write_text("DO THE THING", encoding="utf-8")

    assert cli.load_headless_prompt(None, "briefing.md", tmp_path) == "DO THE THING"


def test_load_headless_prompt_rejects_ambiguous_sources(tmp_path: Path) -> None:
    prompt = tmp_path / "briefing.md"
    prompt.write_text("DO THE THING", encoding="utf-8")

    try:
        cli.load_headless_prompt("inline", "briefing.md", tmp_path)
    except Exception as exc:
        assert "only one prompt source" in str(exc)
    else:
        raise AssertionError("ambiguous prompt sources should fail")


def test_load_headless_prompt_reads_stdin(tmp_path: Path) -> None:
    assert (
        cli.load_headless_prompt(
            None,
            None,
            tmp_path,
            stdin_prompt=True,
            stdin_reader=StringIO("PROMPT FROM STDIN"),
        )
        == "PROMPT FROM STDIN"
    )


def test_load_headless_prompt_blocks_workspace_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-briefing.md"
    outside.write_text("NOPE", encoding="utf-8")

    try:
        cli.load_headless_prompt(None, str(outside), tmp_path)
    except Exception as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("prompt file outside workspace should fail")


def test_build_headless_dry_run_payload_applies_overrides(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from agentx.project_config import set_project_config

    set_project_config(tmp_path, "namespace", "project:target")
    set_project_config(tmp_path, "approval", "deny")
    monkeypatch.setenv("AGENTX_BACKEND", "ollama")

    payload = cli.build_headless_dry_run_payload(
        "hello",
        workspace_override=tmp_path,
        agent_mode=True,
        approval_override="auto-approve",
        backend_override="llama_cpp",
        base_url_override="http://127.0.0.1:8081",
        model_override="gpt-oss:20b",
        timeout_override=123.0,
        run_timeout=9.0,
        max_steps=2,
        save_session=True,
        resume_session="latest",
        no_memory=True,
    )

    assert payload["dry_run"] is True
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["namespace"] == "project:target"
    assert payload["approval"] == "auto"
    assert payload["backend"] == "llama_cpp"
    assert payload["base_url"] == "http://127.0.0.1:8081"
    assert payload["model"] == "gpt-oss:20b"
    assert payload["timeout"] == 123.0
    assert payload["run_timeout"] == 9.0
    assert payload["max_steps"] == 2
    assert payload["no_memory"] is True
    assert payload["save_session"] is True
    assert payload["resume_session"] == "latest"
    assert payload["session_output"] is None
    assert payload["result_output"] is None
    assert payload["prompt_chars"] == 5


def test_build_headless_dry_run_payload_records_result_output(tmp_path: Path) -> None:
    target = tmp_path / "artifacts" / "result.json"

    payload = cli.build_headless_dry_run_payload(
        "hello",
        workspace_override=tmp_path,
        agent_mode=True,
        result_output=target,
        result_output_format="jsonl",
    )

    assert payload["result_output"] == str(target)
    assert payload["result_output_format"] == "jsonl"


def test_build_headless_dry_run_payload_session_output_implies_save(tmp_path: Path) -> None:
    target = tmp_path / "artifacts" / "run.session.jsonl"

    payload = cli.build_headless_dry_run_payload(
        "hello",
        workspace_override=tmp_path,
        agent_mode=True,
        session_output=target,
    )

    assert payload["save_session"] is True
    assert payload["session_output"] == str(target)


def test_build_headless_dry_run_payload_rejects_session_output_with_resume(tmp_path: Path) -> None:
    try:
        cli.build_headless_dry_run_payload(
            "hello",
            workspace_override=tmp_path,
            agent_mode=True,
            resume_session="latest",
            session_output=tmp_path / "run.session.jsonl",
        )
    except Exception as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("session output with resume should fail")


def test_print_prompt_dry_run_json_does_not_call_runner(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    prompt = tmp_path / "briefing.md"
    prompt.write_text("PROMPT", encoding="utf-8")

    def fail_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("dry-run should not call model runner")

    monkeypatch.setattr(cli, "run_print_prompt", fail_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "--workspace",
            str(tmp_path),
            "--prompt-file",
            "briefing.md",
            "--agent",
            "--backend",
            "llama_cpp",
            "--model",
            "local-model",
            "--dry-run",
            "--json",
        ],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["dry_run"] is True
    assert data["workspace"] == str(tmp_path.resolve())
    assert data["backend"] == "llama_cpp"
    assert data["model"] == "local-model"
    assert data["prompt_chars"] == 6


def test_print_prompt_dry_run_jsonl_wraps_dry_run_event(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "should not run")

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--dry-run", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["event"] == "dry_run"
    assert event["data"]["prompt_chars"] == 4
    assert event["data"]["agent_mode"] is True


def test_print_prompt_dry_run_quiet_suppresses_plain_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--dry-run", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_resolve_headless_workspace_accepts_existing_directory(tmp_path: Path) -> None:
    assert cli.resolve_headless_workspace(str(tmp_path)) == tmp_path.resolve()


def test_resolve_headless_workspace_rejects_missing_directory(tmp_path: Path) -> None:
    try:
        cli.resolve_headless_workspace(str(tmp_path / "missing"))
    except Exception as exc:
        assert "workspace is not a directory" in str(exc)
    else:
        raise AssertionError("missing workspace should fail")


def test_resolve_session_store_path_latest_and_name(tmp_path: Path) -> None:
    sessions = tmp_path / ".agentx" / "sessions"
    sessions.mkdir(parents=True)
    first = SessionStore(sessions / "20260101-000000-a.session.jsonl")
    first.append("system", "session_start")
    second = SessionStore(sessions / "20260102-000000-b.session.jsonl")
    second.append("system", "session_start")

    assert cli.resolve_session_store_path(tmp_path, "latest") == second.path
    assert cli.resolve_session_store_path(tmp_path, second.path.name) == second.path
    assert cli.resolve_session_store_path(tmp_path, second.path.stem) == second.path
    assert first.path != second.path


def test_resolve_session_store_path_rejects_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.session.jsonl"
    outside.write_text("{}", encoding="utf-8")

    try:
        cli.resolve_session_store_path(tmp_path, str(outside))
    except FileNotFoundError as exc:
        assert "Saved headless session not found" in str(exc)
    else:
        raise AssertionError("outside session path should be rejected")


def test_resolve_headless_session_output_rejects_escape_and_existing_file(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.session.jsonl"
    existing = tmp_path / "existing.session.jsonl"
    existing.write_text("existing", encoding="utf-8")

    try:
        cli.resolve_headless_session_output(tmp_path, str(outside))
    except Exception as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("outside session output should fail")

    try:
        cli.resolve_headless_session_output(tmp_path, "existing.session.jsonl")
    except Exception as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing session output should fail")


def test_resolve_headless_session_output_accepts_workspace_path(tmp_path: Path) -> None:
    assert (
        cli.resolve_headless_session_output(tmp_path, "artifacts/run.session.jsonl")
        == tmp_path / "artifacts" / "run.session.jsonl"
    )


def test_resolve_headless_result_output_rejects_escape_and_existing_file(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-result.json"
    existing = tmp_path / "existing-result.json"
    existing.write_text("existing", encoding="utf-8")

    try:
        cli.resolve_headless_result_output(tmp_path, str(outside))
    except Exception as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("outside result output should fail")

    try:
        cli.resolve_headless_result_output(tmp_path, "existing-result.json")
    except Exception as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing result output should fail")


def test_resolve_headless_result_output_accepts_workspace_path(tmp_path: Path) -> None:
    assert (
        cli.resolve_headless_result_output(tmp_path, "artifacts/result.json")
        == tmp_path / "artifacts" / "result.json"
    )


def test_resolve_headless_result_output_format_defaults_from_stdout() -> None:
    assert cli.resolve_headless_result_output_format(None, stdout_format="plain") == "json"
    assert cli.resolve_headless_result_output_format("auto", stdout_format="json") == "json"
    assert cli.resolve_headless_result_output_format("auto", stdout_format="jsonl") == "jsonl"
    assert cli.resolve_headless_result_output_format("jsonl", stdout_format="plain") == "jsonl"
    assert cli.resolve_headless_result_output_format("json", stdout_format="jsonl") == "json"


def test_resolve_headless_result_output_format_rejects_unknown() -> None:
    with pytest.raises(Exception, match="result output format"):
        cli.resolve_headless_result_output_format("yaml", stdout_format="plain")


def test_headless_run_stats_summarizes_session_state() -> None:
    session = SimpleNamespace(
        message_count=9,
        context_tokens_estimate=1234,
        error_history=[object(), object()],
        compaction_count=1,
        model_turn_count=4,
        tool_call_count=2,
        reflection_count=1,
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
    assert stats["model_turn_count"] == 4
    assert stats["tool_call_count"] == 2
    assert stats["reflection_count"] == 1
    assert stats["pending_verifies"] == ["src/a.py"]
    assert stats["task_counts"] == {
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "blocked": 1,
    }


def test_headless_handoff_summary_recommends_takeover_steps() -> None:
    summary = cli.headless_handoff_summary(
        termination="final_failed",
        failing_tools=["run_tests"],
        recent_errors=[
            {
                "type": "execution_error",
                "tool": "run_tests",
                "message": "pytest failed",
                "attempt_count": 1,
            }
        ],
        recovery_suggestions=[
            {
                "action": "verify_assumption",
                "confidence": 0.75,
                "description": "read files",
                "rationale": "state stale",
            }
        ],
        pending_verifies=["src/a.py"],
        stats={"task_counts": {"in_progress": 1}},
    )

    assert summary["status"] == "final_failed"
    assert summary["needs_handoff"] is True
    assert summary["failing_tools"] == ["run_tests"]
    assert summary["pending_verifies"] == ["src/a.py"]
    assert summary["task_counts"] == {"in_progress": 1}
    assert summary["last_error"]["message"] == "pytest failed"
    assert summary["recovery_actions"] == ["verify_assumption"]
    assert summary["primary_recovery"] == {
        "action": "verify_assumption",
        "confidence": 0.75,
        "description": "read files",
        "rationale": "state stale",
    }
    assert summary["recovery_checklist"] == [
        "Inspect and verify pending edited paths before new edits.",
        "Review failing tool output for: run_tests.",
        "Start from last_error tool=run_tests type=execution_error.",
        "Read the relevant source and test files before editing.",
        "Run the smallest targeted verification that can prove or disprove the assumption.",
    ]
    assert summary["next_steps"] == [
        "Verify pending edited paths before making more changes.",
        "Inspect or rerun failing tool(s): run_tests.",
        "Apply recovery action: verify_assumption.",
        "Do not treat the final answer as done; resolve failing tools or pending verifies first.",
    ]


def test_headless_handoff_summary_for_max_steps_mentions_resume() -> None:
    summary = cli.headless_handoff_summary(
        termination="max_steps_exceeded",
        failing_tools=[],
        recent_errors=[],
        recovery_suggestions=[],
        pending_verifies=[],
        stats={"task_counts": {}},
    )

    assert summary["needs_handoff"] is True
    assert "Resume from the saved session" in summary["next_steps"][0]


def test_headless_log_summary_summarizes_tool_outcomes_and_errors() -> None:
    session = SimpleNamespace(
        last_termination="final_failed",
        _tool_outcomes={"run_tests": False, "read_file": True},
        error_history=[
            ErrorContext(
                error_type=ErrorType.EXECUTION_ERROR,
                tool_name="run_tests",
                error_message="pytest failed\nwith details",
                attempt_count=2,
            )
        ],
        pending_verifies={"src/a.py"},
        last_recovery_suggestion_details=[
            {
                "action": "verify_assumption",
                "confidence": 0.75,
                "description": "read the file before editing",
                "rationale": "state may be stale",
            }
        ],
    )

    summary = cli.headless_log_summary(session)  # type: ignore[arg-type]

    assert summary["termination"] == "final_failed"
    assert summary["tool_outcomes"] == {"read_file": True, "run_tests": False}
    assert summary["successful_tools"] == ["read_file"]
    assert summary["failing_tools"] == ["run_tests"]
    assert summary["pending_verifies"] == ["src/a.py"]
    assert summary["recent_errors"] == [
        {
            "type": "execution_error",
            "tool": "run_tests",
            "message": "pytest failed\nwith details",
            "attempt_count": 2,
        }
    ]
    assert summary["recovery_suggestions"] == [
        {
            "action": "verify_assumption",
            "confidence": 0.75,
            "description": "read the file before editing",
            "rationale": "state may be stale",
        }
    ]
    assert summary["handoff_summary"]["status"] == "final_failed"
    assert summary["handoff_summary"]["needs_handoff"] is True
    assert summary["handoff_summary"]["failing_tools"] == ["run_tests"]
    assert summary["handoff_summary"]["pending_verifies"] == ["src/a.py"]
    assert summary["handoff_summary"]["recovery_actions"] == ["verify_assumption"]
    assert summary["handoff_summary"]["primary_recovery"] == {
        "action": "verify_assumption",
        "confidence": 0.75,
        "description": "read the file before editing",
        "rationale": "state may be stale",
    }
    assert summary["handoff_summary"]["recovery_checklist"] == [
        "Inspect and verify pending edited paths before new edits.",
        "Review failing tool output for: run_tests.",
        "Start from last_error tool=run_tests type=execution_error.",
        "Read the relevant source and test files before editing.",
        "Run the smallest targeted verification that can prove or disprove the assumption.",
    ]


def test_headless_log_summary_falls_back_to_recovery_actions() -> None:
    session = SimpleNamespace(
        last_termination="max_steps_exceeded",
        _tool_outcomes={},
        error_history=[],
        pending_verifies=set(),
        last_recovery_suggestions=["backtrack", "change_strategy"],
    )

    summary = cli.headless_log_summary(session)  # type: ignore[arg-type]

    assert summary["recovery_suggestions"] == [
        {"action": "backtrack"},
        {"action": "change_strategy"},
    ]


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


def test_print_prompt_json_output_catches_runtime_exception(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def fail_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        raise TimeoutError("model timed out")

    monkeypatch.setattr(cli, "run_print_prompt", fail_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 2
    assert data["termination"] == "runtime_error"
    assert data["log_summary"]["recent_errors"][0]["message"] == "TimeoutError: model timed out"
    assert "Traceback" not in result.output


def test_print_prompt_json_output_catches_run_timeout(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def slow_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        time.sleep(1)
        return cli.HeadlessRunResult(output="late", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", slow_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--run-timeout", "0.01", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 124
    assert data["termination"] == "timeout"
    assert data["log_summary"]["recent_errors"][0]["type"] == "timeout"


def test_print_prompt_plain_output_catches_runtime_exception(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def fail_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(cli, "run_print_prompt", fail_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent"])

    assert result.exit_code == 2
    assert "runtime error: RuntimeError: backend unavailable" in result.output
    assert "Traceback" not in result.output


def test_print_prompt_output_format_json_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["output"] == "ok"
    assert data["termination"] == "final_success"
    assert captured["suppress_trace"] is True


def test_print_prompt_output_format_jsonl_wraps_result_event(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["event"] == "result"
    assert event["data"]["output"] == "ok"
    assert event["data"]["termination"] == "final_success"


def test_print_prompt_result_output_writes_json_artifact(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "result.json"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "-p",
            "demo",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--result-output",
            "artifacts/result.json",
            "--quiet",
        ],
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert result.output == ""
    assert payload["output"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["termination"] == "final_success"


def test_print_prompt_result_output_writes_jsonl_artifact(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "result.jsonl"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="failed", termination="final_failed", failing_tools=("run_tests",))

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "-p",
            "demo",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--output-format",
            "jsonl",
            "--result-output",
            "artifacts/result.jsonl",
        ],
    )
    event = json.loads(result_path.read_text(encoding="utf-8"))
    parsed = cli.load_headless_payload_file(result_path)

    assert result.exit_code == 1
    assert event["event"] == "result"
    assert event["data"]["termination"] == "final_failed"
    assert parsed["failing_tools"] == ["run_tests"]


def test_print_prompt_result_output_format_jsonl_with_plain_stdout(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "result.jsonl"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "-p",
            "demo",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--result-output",
            "artifacts/result.jsonl",
            "--result-output-format",
            "jsonl",
        ],
    )
    event = json.loads(result_path.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert result.output == "ok\n"
    assert event["event"] == "result"
    assert event["data"]["output"] == "ok"


def test_print_prompt_result_output_format_json_with_jsonl_stdout(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "result.json"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "-p",
            "demo",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--output-format",
            "jsonl",
            "--result-output",
            "artifacts/result.json",
            "--result-output-format",
            "json",
        ],
    )
    stdout_event = json.loads(result.output)
    artifact = json.loads(result_path.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert stdout_event["event"] == "result"
    assert artifact["output"] == "ok"
    assert "event" not in artifact


def test_print_prompt_quiet_suppresses_plain_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(output="SHOULD_NOT_PRINT", termination="final_success"),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_print_prompt_quiet_keeps_json_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(output="ok", termination="final_success"),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--quiet", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["output"] == "ok"


def test_print_prompt_uses_prompt_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    prompt = tmp_path / "briefing.md"
    prompt.write_text("PROMPT FROM FILE", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["--prompt-file", "briefing.md", "--agent", "--output-format", "json"],
        env={"AGENTX_WORKSPACE": str(tmp_path)},
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "PROMPT FROM FILE"
    assert captured["agent_mode"] is True
    assert data["output"] == "ok"


def test_print_prompt_workspace_option_controls_prompt_file_and_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    runner = CliRunner()
    prompt = tmp_path / "briefing.md"
    prompt.write_text("PROMPT FROM WORKSPACE OPTION", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["--workspace", str(tmp_path), "--prompt-file", "briefing.md", "--agent", "--output-format", "json"],
    )

    assert result.exit_code == 0
    assert captured["args"][0] == "PROMPT FROM WORKSPACE OPTION"
    assert captured["workspace_override"] == tmp_path.resolve()


def test_print_prompt_uses_stdin(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["--stdin", "--agent", "--output-format", "json"],
        input="PROMPT FROM STDIN",
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "PROMPT FROM STDIN"
    assert captured["agent_mode"] is True
    assert data["output"] == "ok"


def test_print_prompt_rejects_unknown_output_format(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "should not run")

    result = runner.invoke(cli.app, ["-p", "demo", "--output-format", "yaml"])

    assert result.exit_code != 0
    assert "plain, json" in result.output


def test_print_prompt_forwards_session_flags(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path="/tmp/s.session.jsonl")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["-p", "demo", "--agent", "--save-session", "--resume-session", "latest", "--no-memory", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["save_session"] is True
    assert captured["resume_session"] == "latest"
    assert captured["session_output_path"] is None
    assert captured["no_memory"] is True
    assert captured["suppress_trace"] is True
    assert captured["max_steps"] is None
    assert captured["workspace_override"] is None
    assert captured["approval_override"] is None
    assert captured["backend_override"] is None
    assert captured["base_url_override"] is None
    assert captured["model_override"] is None
    assert captured["timeout_override"] is None
    assert data["session_path"] == "/tmp/s.session.jsonl"


def test_print_prompt_forwards_session_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path=str(Path.cwd() / "artifacts/run.session.jsonl"))

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["-p", "demo", "--agent", "--session-output", "artifacts/run.session.jsonl", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["session_output_path"] == Path.cwd() / "artifacts" / "run.session.jsonl"
    assert data["session_path"].endswith("artifacts/run.session.jsonl")


def test_print_prompt_forwards_backend_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--backend", "llama_cpp"])

    assert result.exit_code == 0
    assert captured["backend_override"] == "llama_cpp"


def test_print_prompt_forwards_base_url_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--base-url", "http://127.0.0.1:8081"])

    assert result.exit_code == 0
    assert captured["base_url_override"] == "http://127.0.0.1:8081"


def test_print_prompt_forwards_workspace_override(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["workspace_override"] == tmp_path.resolve()


def test_print_prompt_forwards_approval_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--approval", "auto-approve"])

    assert result.exit_code == 0
    assert captured["approval_override"] == "auto-approve"


def test_print_prompt_forwards_model_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--model", "gpt-oss:20b"])

    assert result.exit_code == 0
    assert captured["model_override"] == "gpt-oss:20b"


def test_print_prompt_forwards_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--timeout", "180"])

    assert result.exit_code == 0
    assert captured["timeout_override"] == 180.0


def test_print_prompt_dry_run_includes_run_timeout(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "should not run")

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--run-timeout", "7", "--dry-run", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["run_timeout"] == 7.0


def test_print_prompt_forwards_max_steps(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--max-steps", "2"])

    assert result.exit_code == 0
    assert captured["max_steps"] == 2
    assert "ok" in result.output


def test_run_print_prompt_plan_then_execute_runs_two_phases(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, bool | None]] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=5,
                context_tokens_estimate=100,
                error_history=[],
                compaction_count=0,
                model_turn_count=2,
                tool_call_count=1,
                reflection_count=1,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            calls.append((prompt, plan_only))
            if plan_only:
                return "PLAN_RESULT"
            return "EXECUTION_RESULT"

    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo task",
        namespace="project:test",
        agent_mode=True,
        plan_then_execute=True,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.output == "## Plan\nPLAN_RESULT\n\n## Execution\nEXECUTION_RESULT"
    assert result.phases == (
        {"name": "plan", "output": "PLAN_RESULT"},
        {"name": "execution", "output": "EXECUTION_RESULT"},
    )
    assert result.termination == "final_success"
    assert calls[0][1] is True
    assert "純 PLAN MODE" in calls[0][0]
    assert calls[1][1] is False
    assert "EXECUTE MODE" in calls[1][0]
    assert "PLAN_RESULT" in calls[1][0]


def test_run_print_prompt_uses_model_override(monkeypatch) -> None:  # noqa: ANN001
    seen_models: list[str] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen_models.append(settings.model)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        model_override="gpt-oss:20b",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_models == ["gpt-oss:20b"]


def test_run_print_prompt_uses_base_url_override(monkeypatch) -> None:  # noqa: ANN001
    seen_urls: list[str] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen_urls.append(settings.ollama_url)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        base_url_override="http://127.0.0.1:8081",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_urls == ["http://127.0.0.1:8081"]


def test_run_print_prompt_uses_workspace_override_and_project_config(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    from agentx.project_config import set_project_config

    seen: list[tuple[Path, str]] = []
    set_project_config(tmp_path, "model", "gemma4:e2b")

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen.append((settings.workspace, settings.model))
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace=None,
        agent_mode=True,
        workspace_override=tmp_path,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen == [(tmp_path.resolve(), "gemma4:e2b")]


def test_run_print_prompt_uses_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    seen_timeouts: list[float] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen_timeouts.append(settings.ollama_timeout)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        timeout_override=180.0,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_timeouts == [180.0]


def test_run_print_prompt_approval_override_wins_over_project_config(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    from agentx.approval import ApprovalPolicy
    from agentx.project_config import set_project_config

    seen_modes: list[str | None] = []
    set_project_config(tmp_path, "approval", "deny")

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, approval_policy=None, **kwargs):  # noqa: ANN001
        assert isinstance(approval_policy, ApprovalPolicy)
        seen_modes.append(approval_policy.mode.value)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        workspace_override=tmp_path,
        approval_override="auto-approve",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_modes == ["auto"]


def test_run_print_prompt_rejects_invalid_approval_override() -> None:
    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        approval_override="yes",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.termination == "invalid_action"
    assert "approval must be one of" in result.output


def test_run_print_prompt_forwards_backend_override_to_runtime(monkeypatch) -> None:  # noqa: ANN001
    seen_backends: list[str | None] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, backend_override=None, **kwargs):  # noqa: ANN001
        seen_backends.append(backend_override)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        backend_override="llama_cpp",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_backends == ["llama_cpp"]


def test_run_print_prompt_forwards_no_memory_to_runtime(monkeypatch) -> None:  # noqa: ANN001
    seen_no_memory: list[bool | None] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, no_memory=False, **kwargs):  # noqa: ANN001
        seen_no_memory.append(no_memory)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        no_memory=True,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_no_memory == [True]


def test_run_print_prompt_writes_explicit_session_output(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    class FakeAgentLoop:
        def __init__(self, *args, settings=None, **kwargs) -> None:  # noqa: ANN002, ANN003
            from agentx.loop import AgentSession
            from agentx.tools import ToolRegistry

            self.session = AgentSession(
                settings=settings or make_settings(tmp_path, learning_enabled=False),
                ollama=SimpleNamespace(chat=lambda *args, **kwargs: '{"type":"final","content":"done"}'),
                tools=ToolRegistry([]),
                memory=None,
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            return "ok"

    target = tmp_path / "artifacts" / "run.session.jsonl"
    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        workspace_override=tmp_path,
        session_output_path=target,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.session_path == str(target)
    assert target.exists()
    assert "session_start" in target.read_text(encoding="utf-8")


def test_run_print_prompt_runtime_error_preserves_explicit_session_output(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    from helpers import make_settings

    class FakeAgentLoop:
        def __init__(self, *args, settings=None, **kwargs) -> None:  # noqa: ANN002, ANN003
            from agentx.loop import AgentSession
            from agentx.tools import ToolRegistry

            self.session = AgentSession(
                settings=settings or make_settings(tmp_path, learning_enabled=False),
                ollama=SimpleNamespace(chat=lambda *args, **kwargs: '{"type":"final","content":"done"}'),
                tools=ToolRegistry([]),
                memory=None,
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None, cancel_event=None) -> str:
            raise TimeoutError("model timed out")

    target = tmp_path / "artifacts" / "run.session.jsonl"
    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        workspace_override=tmp_path,
        session_output_path=target,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.termination == "runtime_error"
    assert result.session_path == str(target)
    assert target.exists()


def test_run_print_prompt_rejects_session_output_with_resume(tmp_path: Path) -> None:
    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        workspace_override=tmp_path,
        resume_session="latest",
        session_output_path=tmp_path / "run.session.jsonl",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.termination == "invalid_action"
    assert "cannot be combined" in result.output


def test_build_runtime_backend_override_wins_over_env(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    seen: dict[str, object] = {}

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "base_url": base_url, "model": model, "timeout": timeout})
        return object()

    monkeypatch.setenv("AGENTX_BACKEND", "ollama")
    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    cli.build_runtime(make_settings(tmp_path), backend_override="llama_cpp")

    assert seen["name"] == "llama_cpp"


def test_build_runtime_uses_timeout_from_settings(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    seen: dict[str, object] = {}

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "timeout": timeout})
        return object()

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    cli.build_runtime(make_settings(tmp_path).with_updates(ollama_timeout=222.0))

    assert seen["timeout"] == 222.0


def test_build_runtime_uses_base_url_from_settings(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    seen: dict[str, object] = {}

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "base_url": base_url})
        return object()

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    cli.build_runtime(make_settings(tmp_path).with_updates(ollama_url="http://127.0.0.1:8081"))

    assert seen["base_url"] == "http://127.0.0.1:8081"


def test_build_runtime_no_memory_uses_null_memory_client(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings
    from agentx.memory_hall import NullMemoryClient

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", lambda *args, **kwargs: object())

    _, memory, tools = cli.build_runtime(make_settings(tmp_path), no_memory=True)

    assert isinstance(memory, NullMemoryClient)
    assert tools.run("memory_search", {"query": "anything", "namespace": "project:test"}).content == "[]"


def test_ask_uses_shared_headless_runner_and_forwards_session_flags(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path="/tmp/s.session.jsonl")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["ask", "demo", "--save-session", "--resume-session", "latest", "--max-steps", "3", "--no-memory", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "demo"
    assert captured["agent_mode"] is True
    assert captured["return_metadata"] is True
    assert captured["suppress_trace"] is True
    assert captured["save_session"] is True
    assert captured["resume_session"] == "latest"
    assert captured["session_output_path"] is None
    assert captured["no_memory"] is True
    assert captured["max_steps"] == 3
    assert captured["plan_then_execute"] is False
    assert captured["workspace_override"] is None
    assert captured["approval_override"] is None
    assert captured["backend_override"] is None
    assert captured["base_url_override"] is None
    assert captured["model_override"] is None
    assert captured["timeout_override"] is None
    assert data["session_path"] == "/tmp/s.session.jsonl"


def test_ask_forwards_session_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path=str(Path.cwd() / "artifacts/ask.session.jsonl"))

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--session-output", "artifacts/ask.session.jsonl", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["session_output_path"] == Path.cwd() / "artifacts" / "ask.session.jsonl"
    assert data["session_path"].endswith("artifacts/ask.session.jsonl")


def test_ask_result_output_writes_json_artifact(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "ask-result.json"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "ask",
            "demo",
            "--workspace",
            str(tmp_path),
            "--result-output",
            "artifacts/ask-result.json",
            "--quiet",
        ],
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert result.output == ""
    assert payload["output"] == "ok"
    assert payload["exit_code"] == 0


def test_ask_result_output_format_jsonl_with_plain_stdout(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    runner = CliRunner()
    result_path = tmp_path / "artifacts" / "ask-result.jsonl"

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        [
            "ask",
            "demo",
            "--workspace",
            str(tmp_path),
            "--result-output",
            "artifacts/ask-result.jsonl",
            "--result-output-format",
            "jsonl",
        ],
    )
    event = json.loads(result_path.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert result.output == "ok\n"
    assert event["event"] == "result"
    assert event["data"]["output"] == "ok"


def test_ask_forwards_plan_then_execute(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--plan-then-execute"])

    assert result.exit_code == 0
    assert captured["plan_then_execute"] is True


def test_ask_forwards_backend_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--backend", "llama_cpp"])

    assert result.exit_code == 0
    assert captured["backend_override"] == "llama_cpp"


def test_ask_forwards_base_url_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--base-url", "http://127.0.0.1:8081"])

    assert result.exit_code == 0
    assert captured["base_url_override"] == "http://127.0.0.1:8081"


def test_ask_forwards_workspace_override(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["workspace_override"] == tmp_path.resolve()


def test_ask_forwards_approval_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--approval", "off"])

    assert result.exit_code == 0
    assert captured["approval_override"] == "off"


def test_ask_forwards_model_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--model", "gpt-oss:20b"])

    assert result.exit_code == 0
    assert captured["model_override"] == "gpt-oss:20b"


def test_ask_forwards_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--timeout", "180"])

    assert result.exit_code == 0
    assert captured["timeout_override"] == 180.0


def test_ask_json_output_catches_run_timeout(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def slow_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        time.sleep(1)
        return cli.HeadlessRunResult(output="late", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", slow_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--run-timeout", "0.01", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 124
    assert data["termination"] == "timeout"


def test_ask_output_format_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["output"] == "ok"
    assert captured["suppress_trace"] is True


def test_ask_output_format_jsonl(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--output-format", "jsonl"])
    event = json.loads(result.output)

    assert result.exit_code == 0
    assert event["event"] == "result"
    assert event["data"]["output"] == "ok"


def test_ask_quiet_suppresses_plain_output(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(output="SHOULD_NOT_PRINT", termination="final_success"),
    )

    result = runner.invoke(cli.app, ["ask", "demo", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_ask_dry_run_plain(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = runner.invoke(cli.app, ["ask", "demo", "--dry-run", "--max-steps", "3"])

    assert result.exit_code == 0
    assert "headless dry run" in result.output
    assert "agent_mode: True" in result.output
    assert "max_steps: 3" in result.output
