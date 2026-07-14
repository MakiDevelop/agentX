import json

from typer.testing import CliRunner

from agentx.cli import app, tool_plan_exit_code, tool_plan_payload
from agentx.config import Settings


def test_tool_plan_payload_allows_green_tool(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "read_file", '{"path":"README.md"}')

    assert payload["schema"] == "agentx.tool_plan.v1"
    assert payload["ok"] is True
    assert payload["exists"] is True
    assert payload["canonical_tool"] == "read_file"
    assert payload["risk"] == "GREEN"
    assert payload["approval_required"] is False
    assert payload["args"] == {"path": "README.md"}
    assert payload["command_plan"] is None
    assert payload["blockers"] == []


def test_tool_plan_payload_resolves_alias_and_marks_yellow(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(
        Settings(workspace=tmp_path),
        "search_replace",
        '{"path":"README.md","edits":[{"oldText":"old","newText":"new"}]}',
    )

    assert payload["ok"] is True
    assert payload["requested_tool"] == "search_replace"
    assert payload["canonical_tool"] == "edit_file"
    assert payload["risk"] == "YELLOW"
    assert payload["approval_required"] is True
    assert "search_replace" in payload["aliases"]
    assert "Confirm YELLOW approval before execution" in payload["next_commands"]


def test_tool_plan_payload_blocks_missing_required_write_args(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "edit_file", '{"path":"README.md"}')

    assert payload["ok"] is False
    assert "missing_edits" in payload["blockers"]


def test_tool_plan_payload_blocks_unsafe_write_path(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "write_file", '{"path":".agentx/state.json","content":"{}"}')

    assert payload["ok"] is False
    assert payload["risk"] == "YELLOW"
    assert "unsafe_write_path" in payload["blockers"]


def test_tool_plan_payload_integrates_run_command_policy(tmp_path) -> None:  # noqa: ANN001
    good = tool_plan_payload(Settings(workspace=tmp_path), "run_command", '{"command":"uv run pytest -q"}')
    bad = tool_plan_payload(Settings(workspace=tmp_path), "run_command", '{"command":"npm test"}')

    assert good["ok"] is True
    assert good["blockers"] == []
    assert good["command_plan"]["schema"] == "agentx.command_plan.v1"  # type: ignore[index]
    assert good["command_plan"]["matched_policy"] == "allowed_command"  # type: ignore[index]
    assert good["command_plan"]["allowed"] is True  # type: ignore[index]
    assert bad["ok"] is False
    assert bad["command_plan"]["schema"] == "agentx.command_plan.v1"  # type: ignore[index]
    assert bad["command_plan"]["matched_policy"] == "build_command"  # type: ignore[index]
    assert "run_command_requires_green_allowlist" in bad["blockers"]


def test_tool_plan_payload_blocks_unknown_tool(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "not_a_tool", "{}")

    assert payload["ok"] is False
    assert payload["exists"] is False
    assert payload["risk"] == "UNKNOWN"
    assert payload["blockers"] == ["unknown_tool"]


def test_tool_plan_payload_blocks_invalid_args_json(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "read_file", "{")

    assert payload["ok"] is False
    assert payload["exists"] is True
    assert "invalid_args_json" in payload["blockers"]


def test_tool_plan_json_outputs_payload() -> None:
    result = CliRunner().invoke(app, ["tool-plan", "read_file", "--args-json", '{"path":"README.md"}', "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.tool_plan.v1"
    assert payload["canonical_tool"] == "read_file"
    assert payload["ok"] is True


def test_tool_plan_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["tool-plan", "read_file", "--args-json", '{"path":"README.md"}', "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "tool_plan"
    assert envelope["data"]["schema"] == "agentx.tool_plan.v1"


def test_tool_plan_fail_on_blocker_exits_one_but_prints_payload() -> None:
    result = CliRunner().invoke(
        app,
        ["tool-plan", "write_file", "--args-json", '{"path":".agentx/state.json","content":"{}"}', "--json", "--fail-on-blocker"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "unsafe_write_path" in payload["blockers"]


def test_tool_plan_exit_code_is_opt_in(tmp_path) -> None:  # noqa: ANN001
    payload = tool_plan_payload(Settings(workspace=tmp_path), "not_a_tool", "{}")

    assert tool_plan_exit_code(payload, fail_on_blocker=False) == 0
    assert tool_plan_exit_code(payload, fail_on_blocker=True) == 1
