import json

from typer.testing import CliRunner

from agentx.cli import app, command_plan_exit_code, command_plan_payload
from agentx.config import Settings


def test_command_plan_payload_allows_green_command(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "uv run pytest -q")

    assert payload["schema"] == "agentx.command_plan.v1"
    assert payload["ok"] is True
    assert payload["allowed"] is True
    assert payload["risk"] == "GREEN"
    assert payload["approval_required"] is False
    assert payload["matched_policy"] == "allowed_command"
    assert payload["tool"] == "run_command"
    assert payload["tool_args"] == {"command": "uv run pytest -q"}
    assert payload["blockers"] == []


def test_command_plan_payload_marks_build_command_yellow(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "npm test")

    assert payload["ok"] is True
    assert payload["allowed"] is True
    assert payload["risk"] == "YELLOW"
    assert payload["approval_required"] is True
    assert payload["matched_policy"] == "build_command"
    assert payload["tool"] == "run_build_command"
    assert "Confirm YELLOW approval before execution" in payload["next_commands"]


def test_command_plan_payload_blocks_destructive_command(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "git clean -fd")

    assert payload["ok"] is False
    assert payload["allowed"] is False
    assert payload["risk"] == "RED"
    assert "destructive_git_clean" in payload["blockers"]
    assert "command_not_allowlisted" not in payload["blockers"]


def test_command_plan_payload_blocks_destructive_flags(tmp_path) -> None:  # noqa: ANN001
    rsync_payload = command_plan_payload(Settings(workspace=tmp_path), "rsync --delete src dst")
    git_payload = command_plan_payload(Settings(workspace=tmp_path), "git push origin main --force-with-lease=main")

    assert rsync_payload["risk"] == "RED"
    assert "destructive_transfer_flag" in rsync_payload["blockers"]
    assert git_payload["risk"] == "RED"
    assert "destructive_git_force_push" in git_payload["blockers"]


def test_command_plan_payload_blocks_unknown_command(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "python manage.py migrate")

    assert payload["ok"] is False
    assert payload["allowed"] is False
    assert payload["risk"] == "UNKNOWN"
    assert payload["blockers"] == ["command_not_allowlisted"]
    assert payload["tool"] is None


def test_command_plan_payload_allows_agentx_capability(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "agentx gate --json --fail-on-blocker")

    assert payload["ok"] is True
    assert payload["allowed"] is True
    assert payload["risk"] == "GREEN"
    assert payload["matched_policy"] == "agentx_cli_capability"
    assert payload["resolved_argv"] == ["agentx", "gate", "--json", "--fail-on-blocker"]


def test_command_plan_payload_marks_agentx_agent_run_yellow(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(
        Settings(workspace=tmp_path),
        "agentx -p 'continue' --agent --json --artifact-dir .agentx/runs/latest --quiet",
    )

    assert payload["ok"] is True
    assert payload["allowed"] is True
    assert payload["risk"] == "YELLOW"
    assert payload["approval_required"] is True
    assert payload["matched_policy"] == "agentx_headless"
    assert payload["tool_args"] == {
        "agent_mode": True,
        "prompt_source": "inline_prompt",
        "workspace_override": False,
        "artifact_dir": ".agentx/runs/latest",
        "result_output": None,
        "session_output": None,
        "handoff_briefing_output": None,
        "save_session": False,
        "resume_session": None,
        "quiet": True,
        "output_format": "json",
    }
    assert payload["next_commands"] == ["agentx inspect --json", "agentx artifacts --json"]


def test_command_plan_payload_marks_agentx_prompt_file_metadata(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(
        Settings(workspace=tmp_path),
        "agentx --prompt-file briefing.md --output-format jsonl --resume-session latest --save-session",
    )

    assert payload["ok"] is True
    assert payload["risk"] == "GREEN"
    assert payload["approval_required"] is False
    assert payload["tool_args"]["prompt_source"] == "prompt_file"  # type: ignore[index]
    assert payload["tool_args"]["resume_session"] == "latest"  # type: ignore[index]
    assert payload["tool_args"]["save_session"] is True  # type: ignore[index]
    assert payload["tool_args"]["output_format"] == "jsonl"  # type: ignore[index]
    assert payload["next_commands"] == ["agentx inspect --json", "agentx next --json"]


def test_command_plan_payload_marks_agentx_equals_options(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(
        Settings(workspace=tmp_path),
        "agentx --prompt-file=briefing.md --agent --output-format=jsonl --resume-session=latest "
        "--artifact-dir=.agentx/runs/latest --workspace=.",
    )

    assert payload["ok"] is True
    assert payload["matched_policy"] == "agentx_headless"
    assert payload["tool_args"]["prompt_source"] == "prompt_file"  # type: ignore[index]
    assert payload["tool_args"]["artifact_dir"] == ".agentx/runs/latest"  # type: ignore[index]
    assert payload["tool_args"]["resume_session"] == "latest"  # type: ignore[index]
    assert payload["tool_args"]["workspace_override"] is True  # type: ignore[index]
    assert payload["tool_args"]["output_format"] == "jsonl"  # type: ignore[index]
    assert payload["next_commands"] == ["agentx inspect --json", "agentx artifacts --json"]


def test_command_plan_payload_blocks_agentx_artifact_output_conflicts(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(
        Settings(workspace=tmp_path),
        "agentx -p x --agent --artifact-dir .agentx/runs/latest --result-output result.json --json",
    )

    assert payload["ok"] is False
    assert payload["allowed"] is False
    assert payload["matched_policy"] == "agentx_headless"
    assert "headless_artifact_dir_conflicts_with_output_options" in payload["blockers"]


def test_command_plan_payload_blocks_agentx_artifact_requires_agent(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "agentx -p x --artifact-dir .agentx/runs/latest --json")

    assert payload["ok"] is False
    assert payload["allowed"] is False
    assert "headless_artifact_dir_requires_agent" in payload["blockers"]


def test_command_plan_payload_blocks_agentx_session_resume_conflict(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(
        Settings(workspace=tmp_path),
        "agentx --prompt-file briefing.md --session-output run.session.jsonl --resume-session latest",
    )

    assert payload["ok"] is False
    assert payload["allowed"] is False
    assert "headless_session_output_conflicts_with_resume_session" in payload["blockers"]


def test_command_plan_json_outputs_payload() -> None:
    result = CliRunner().invoke(app, ["command-plan", "uv run pytest -q", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.command_plan.v1"
    assert payload["command"] == "uv run pytest -q"
    assert payload["allowed"] is True
    assert payload["tool"] == "run_command"


def test_command_plan_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["command-plan", "npm test", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "command_plan"
    assert envelope["data"]["schema"] == "agentx.command_plan.v1"
    assert envelope["data"]["risk"] == "YELLOW"


def test_command_plan_fail_on_blocker_exits_one_but_prints_payload() -> None:
    result = CliRunner().invoke(app, ["command-plan", "python manage.py migrate", "--json", "--fail-on-blocker"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.command_plan.v1"
    assert payload["blockers"] == ["command_not_allowlisted"]


def test_command_plan_exit_code_is_opt_in(tmp_path) -> None:  # noqa: ANN001
    payload = command_plan_payload(Settings(workspace=tmp_path), "python manage.py migrate")

    assert command_plan_exit_code(payload, fail_on_blocker=False) == 0
    assert command_plan_exit_code(payload, fail_on_blocker=True) == 1
