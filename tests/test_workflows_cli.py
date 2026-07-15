import json
import subprocess

from typer.testing import CliRunner

from agentx.cli import app, workflow_catalog_payload, workflow_plan_payload, workflow_run_payload


def test_workflow_catalog_payload_lists_aliases() -> None:
    payload = workflow_catalog_payload()

    assert payload["schema"] == "agentx.workflow_catalog.v1"
    assert payload["query"] is None
    assert payload["count"] >= 5
    workflows = {item["goal"]: item for item in payload["workflows"]}
    assert "Headless bundle" in workflows
    assert "headless" in workflows["Headless bundle"]["aliases"]
    assert workflows["Headless bundle"]["commands"] == [
        'agentx -p "任務" --agent --artifact-dir .agentx/runs/latest --quiet',
        "agentx handoff-resume .agentx/runs/latest --dry-run",
    ]
    assert all(step["runnable"] is True for step in workflows["Headless bundle"]["steps"])
    assert workflows["Headless bundle"]["steps"][0]["kind"] == "agentx_cli"
    assert workflows["Headless bundle"]["steps"][0]["command_plan"]["schema"] == "agentx.command_plan.v1"
    assert workflows["Headless bundle"]["steps"][0]["command_plan"]["risk"] == "YELLOW"
    assert workflows["Headless bundle"]["steps"][1]["command_plan"]["allowed"] is True
    assert "Infra preflight" in workflows
    assert "infra" in workflows["Infra preflight"]["aliases"]
    assert "vps" in workflows["Infra preflight"]["aliases"]
    assert workflows["Infra preflight"]["commands"] == [
        "agentx infra resource-bundle --json",
        "/intent SSH/deploy/cross-machine",
    ]
    assert workflows["Infra preflight"]["steps"][0]["kind"] == "agentx_cli"
    assert workflows["Infra preflight"]["steps"][0]["command_plan"]["schema"] == "agentx.command_plan.v1"
    assert workflows["Infra preflight"]["steps"][0]["command_plan"]["risk"] == "GREEN"
    assert workflows["Infra preflight"]["steps"][2] == {
        "command": "填寫 runtime state block",
        "kind": "instruction",
        "runnable": False,
    }
    assert "Approval audit" in workflows
    assert "audit" in workflows["Approval audit"]["aliases"]
    assert "記憶交接" in workflows
    assert "amh" in workflows["記憶交接"]["aliases"]
    assert workflows["記憶交接"]["commands"] == [
        'agentx memory-read "handoff" --json',
        'agentx memory-write "完成與待辦" --type handoff --json',
        'agentx memory-write "完成與待辦" --type handoff --write --json',
    ]
    assert workflows["記憶交接"]["steps"][0]["command_plan"]["matched_policy"] == "agentx_cli_capability"
    assert "ACE council" in workflows
    assert "ace" in workflows["ACE council"]["aliases"]
    assert "council" in workflows["ACE council"]["aliases"]
    assert workflows["ACE council"]["commands"] == [
        'agentx ace-init SESSION --goal "GOAL" --json',
        'agentx ace-init SESSION --goal "GOAL" --write --json',
        'agentx ace-briefing SESSION --agent gemini --role Reviewer --task "Review manifest" --json',
        'agentx ace-answer SESSION --agent gemini --answer "ANSWER" --summary "SUMMARY" --json',
        "agentx ace-status SESSION --json",
    ]
    assert workflows["ACE council"]["steps"][0]["command_plan"]["schema"] == "agentx.command_plan.v1"
    assert workflows["理解 repo"]["steps"][0]["kind"] == "slash_command"
    assert "command_plan" not in workflows["理解 repo"]["steps"][0]
    assert workflows["小步修改"]["steps"][2] == {"command": "讓 agent 讀檔與改檔", "kind": "instruction", "runnable": False}
    assert "讓 agent 讀檔與改檔" not in workflows["小步修改"]["commands"]


def test_workflow_catalog_payload_filters_by_alias() -> None:
    payload = workflow_catalog_payload("headless")

    assert payload["query"] == "headless"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "Headless bundle"
    assert "--artifact-dir" in payload["workflows"][0]["path"]
    assert payload["workflows"][0]["commands"][0].startswith("agentx -p")
    assert payload["workflows"][0]["steps"][0]["command_plan"]["command"].startswith("agentx -p")


def test_workflow_catalog_payload_filters_infra_alias() -> None:
    payload = workflow_catalog_payload("vps")

    assert payload["query"] == "vps"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "Infra preflight"
    assert payload["workflows"][0]["commands"][0] == "agentx infra resource-bundle --json"
    assert payload["workflows"][0]["steps"][0]["command_plan"]["matched_policy"] == "agentx_cli_capability"


def test_workflow_catalog_payload_filters_memory_alias() -> None:
    payload = workflow_catalog_payload("amh")

    assert payload["query"] == "amh"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "記憶交接"
    assert payload["workflows"][0]["commands"][0] == 'agentx memory-read "handoff" --json'
    assert payload["workflows"][0]["steps"][2]["command_plan"]["risk"] == "YELLOW"


def test_workflow_catalog_payload_filters_ace_alias() -> None:
    payload = workflow_catalog_payload("council")

    assert payload["query"] == "council"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "ACE council"
    assert payload["workflows"][0]["commands"][-1] == "agentx ace-status SESSION --json"
    assert payload["workflows"][0]["steps"][1]["command_plan"]["risk"] == "YELLOW"


def test_workflow_plan_payload_reports_memory_inputs_and_gates(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_plan_payload("memory", workspace=tmp_path)

    assert payload["schema"] == "agentx.workflow_plan.v1"
    assert payload["query"] == "memory"
    assert payload["ok"] is False
    assert payload["workflow"]["goal"] == "記憶交接"  # type: ignore[index]
    assert payload["commands"][0] == 'agentx memory-read "handoff" --json'  # type: ignore[index]
    assert "missing_inputs" in payload["blockers"]  # type: ignore[operator]
    assert payload["inputs_required"] == [  # type: ignore[index]
        {
            "step_index": 2,
            "placeholder": "完成與待辦",
            "description": "handoff content",
            "command": 'agentx memory-write "完成與待辦" --type handoff --json',
        },
        {
            "step_index": 3,
            "placeholder": "完成與待辦",
            "description": "handoff content",
            "command": 'agentx memory-write "完成與待辦" --type handoff --write --json',
        },
    ]
    assert payload["side_effect_gates"][-1]["risk"] == "YELLOW"  # type: ignore[index]
    assert payload["side_effect_gates"][-1]["approval_required"] is True  # type: ignore[index]


def test_workflow_plan_payload_reports_ace_placeholders(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_plan_payload("ace", workspace=tmp_path)

    assert payload["ok"] is False
    placeholders = {item["placeholder"] for item in payload["inputs_required"]}  # type: ignore[index]
    assert {"SESSION", "GOAL", "ANSWER", "SUMMARY"} <= placeholders
    assert len(payload["commands"]) == 5  # type: ignore[arg-type]
    assert payload["side_effect_gates"][1]["risk"] == "YELLOW"  # type: ignore[index]


def test_workflow_plan_payload_applies_memory_inputs(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_plan_payload("memory", workspace=tmp_path, inputs={"完成與待辦": "完成 AMH 交接"})

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["inputs_required"] == []
    assert payload["inputs"] == {"完成與待辦": "完成 AMH 交接"}
    assert payload["ready_commands"] == [
        'agentx memory-read "handoff" --json',
        "agentx memory-write '完成 AMH 交接' --type handoff --json",
        "agentx memory-write '完成 AMH 交接' --type handoff --write --json",
    ]
    assert payload["next_commands"] == payload["ready_commands"]
    assert payload["recommended_command"] == 'agentx memory-read "handoff" --json'
    assert payload["recommended_risk"] == "YELLOW"
    assert payload["side_effect_gates"][-1]["command"] == "agentx memory-write '完成 AMH 交接' --type handoff --write --json"  # type: ignore[index]


def test_workflow_plan_payload_applies_ace_inputs(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_plan_payload(
        "ace",
        workspace=tmp_path,
        inputs={
            "SESSION": "2026-07-15-agentx",
            "GOAL": "Add ACE workflow",
            "ANSWER": "No blocker",
            "SUMMARY": "Gemini found no blocker",
        },
    )

    assert payload["ok"] is True
    assert payload["inputs_required"] == []
    assert payload["ready_commands"][0] == "agentx ace-init 2026-07-15-agentx --goal 'Add ACE workflow' --json"  # type: ignore[index]
    assert payload["ready_commands"][-1] == "agentx ace-status 2026-07-15-agentx --json"  # type: ignore[index]
    gate_commands = {item["command"] for item in payload["side_effect_gates"]}  # type: ignore[index]
    assert "agentx ace-init 2026-07-15-agentx --goal 'Add ACE workflow' --write --json" in gate_commands


def test_workflow_plan_payload_blocks_missing_workflow(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_plan_payload("missing", workspace=tmp_path)

    assert payload["ok"] is False
    assert payload["blockers"] == ["workflow_not_found"]
    assert payload["workflow"] is None
    assert payload["next_commands"] == ["agentx workflows missing --json"]


def test_workflow_run_payload_dry_run_does_not_execute(tmp_path) -> None:  # noqa: ANN001
    payload = workflow_run_payload("memory", workspace=tmp_path, inputs={"完成與待辦": "完成 AMH 交接"})

    assert payload["schema"] == "agentx.workflow_run.v1"
    assert payload["execute"] is False
    assert payload["ok"] is True
    assert payload["execution_allowed"] is False
    assert payload["executed_steps"] == []
    assert payload["stopped_at"] is None
    assert payload["warnings"] == ["dry_run_no_commands_executed"]
    assert payload["plan"]["ready_commands"][1] == "agentx memory-write '完成 AMH 交接' --type handoff --json"  # type: ignore[index]


def test_workflow_run_payload_execute_stops_before_non_agentx_step(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        calls.append((argv, kwargs["cwd"]))
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agentx.cli.subprocess.run", fake_run)

    payload = workflow_run_payload("infra", workspace=tmp_path, execute=True)

    assert payload["ok"] is False
    assert payload["execution_allowed"] is False
    assert calls == [(["agentx", "infra", "resource-bundle", "--json"], tmp_path.resolve())]
    assert payload["executed_steps"][0]["returncode"] == 0  # type: ignore[index]
    assert payload["stopped_at"]["reason"] == "non_agentx_cli_step"  # type: ignore[index]


def test_workflow_run_payload_execute_stops_before_yellow_gate(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "agentx.cli.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )

    payload = workflow_run_payload("memory", workspace=tmp_path, inputs={"完成與待辦": "完成 AMH 交接"}, execute=True)

    assert payload["ok"] is False
    assert payload["stopped_at"]["reason"] == "side_effect_gate"  # type: ignore[index]
    assert payload["stopped_at"]["risk"] == "YELLOW"  # type: ignore[index]


def test_workflow_run_payload_allow_yellow_requires_reason(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    calls = []
    monkeypatch.setattr(
        "agentx.cli.subprocess.run",
        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )

    payload = workflow_run_payload(
        "memory",
        workspace=tmp_path,
        inputs={"完成與待辦": "完成 AMH 交接"},
        execute=True,
        allow_yellow_gates=True,
    )

    assert payload["ok"] is False
    assert payload["stopped_at"] == {"reason": "approval_reason_required"}
    assert payload["approval_receipts"] == []
    assert calls == []


def test_workflow_run_payload_allow_yellow_executes_with_receipt(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agentx.cli.subprocess.run", fake_run)

    payload = workflow_run_payload(
        "memory",
        workspace=tmp_path,
        inputs={"完成與待辦": "完成 AMH 交接"},
        execute=True,
        allow_yellow_gates=True,
        approval_reason="Maki approved workflow memory handoff write",
    )

    assert payload["ok"] is True
    assert payload["stopped_at"] is None
    assert payload["execution_allowed"] is True
    assert len(payload["executed_steps"]) == 3  # type: ignore[arg-type]
    assert calls[-1] == [
        "agentx",
        "memory-write",
        "完成 AMH 交接",
        "--type",
        "handoff",
        "--write",
        "--json",
    ]
    assert payload["approval_receipts"] == [  # type: ignore[index]
        {
            "step_index": 3,
            "command": "agentx memory-write '完成 AMH 交接' --type handoff --write --json",
            "risk": "YELLOW",
            "approval_mode": "workflow-run",
            "source": "allow_yellow_gates",
            "allowed": True,
            "reason": "Maki approved workflow memory handoff write",
        }
    ]


def test_workflows_json_outputs_catalog() -> None:
    result = CliRunner().invoke(app, ["workflows", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.workflow_catalog.v1"
    assert payload["count"] >= 5
    assert any(item["goal"] == "提交收尾" for item in payload["workflows"])
    assert all("steps" in item and "commands" in item for item in payload["workflows"])


def test_workflows_json_accepts_alias_filter() -> None:
    result = CliRunner().invoke(app, ["workflows", "audit", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "audit"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "Approval audit"


def test_workflows_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["workflows", "commit", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "workflows"
    assert envelope["data"]["schema"] == "agentx.workflow_catalog.v1"
    assert envelope["data"]["workflows"][0]["goal"] == "提交收尾"


def test_workflow_plan_json_outputs_payload() -> None:
    result = CliRunner().invoke(app, ["workflow-plan", "memory", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.workflow_plan.v1"
    assert payload["query"] == "memory"
    assert payload["workflow"]["goal"] == "記憶交接"
    assert "missing_inputs" in payload["blockers"]


def test_workflow_plan_json_accepts_input_substitution() -> None:
    result = CliRunner().invoke(
        app,
        [
            "workflow-plan",
            "memory",
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--json",
            "--fail-on-blocker",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["inputs_required"] == []
    assert payload["ready_commands"][1] == "agentx memory-write '完成 AMH 交接' --type handoff --json"


def test_workflow_plan_invalid_input_can_fail_on_blocker() -> None:
    result = CliRunner().invoke(app, ["workflow-plan", "memory", "--input", "bad", "--json", "--fail-on-blocker"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "invalid_input:bad" in payload["blockers"]


def test_workflow_plan_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["workflow-plan", "ace", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "workflow_plan"
    assert envelope["data"]["schema"] == "agentx.workflow_plan.v1"


def test_workflow_plan_fail_on_blocker_exits_nonzero() -> None:
    result = CliRunner().invoke(app, ["workflow-plan", "ace", "--json", "--fail-on-blocker"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["blockers"] == ["missing_inputs"]


def test_workflow_run_json_outputs_dry_run_payload() -> None:
    result = CliRunner().invoke(
        app,
        ["workflow-run", "memory", "--input", "完成與待辦=完成 AMH 交接", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.workflow_run.v1"
    assert payload["execute"] is False
    assert payload["plan"]["ready_commands"][1] == "agentx memory-write '完成 AMH 交接' --type handoff --json"


def test_workflow_run_result_output_writes_json_artifact(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "workflow-run",
            "memory",
            "--workspace",
            str(tmp_path),
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--result-output",
            "artifacts/workflow-run.json",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    stdout_payload = json.loads(result.output)
    target = tmp_path / "artifacts/workflow-run.json"
    artifact_payload = json.loads(target.read_text(encoding="utf-8"))
    assert artifact_payload["schema"] == "agentx.workflow_run.v1"
    assert artifact_payload["execute"] is False
    assert artifact_payload["result_output"] == str(target)
    assert artifact_payload["result_output_format"] == "json"
    assert stdout_payload == artifact_payload


def test_workflow_run_result_output_writes_jsonl_artifact(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "workflow-run",
            "memory",
            "--workspace",
            str(tmp_path),
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--result-output",
            "artifacts/workflow-run.jsonl",
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    stdout_envelope = json.loads(result.output)
    target = tmp_path / "artifacts/workflow-run.jsonl"
    artifact_envelope = json.loads(target.read_text(encoding="utf-8"))
    assert artifact_envelope["event"] == "workflow_run"
    assert artifact_envelope["data"]["schema"] == "agentx.workflow_run.v1"
    assert artifact_envelope["data"]["result_output"] == str(target)
    assert artifact_envelope["data"]["result_output_format"] == "jsonl"
    assert stdout_envelope == artifact_envelope


def test_workflow_run_result_output_rejects_existing_file(tmp_path) -> None:  # noqa: ANN001
    target = tmp_path / "existing.json"
    target.write_text("already here\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "workflow-run",
            "memory",
            "--workspace",
            str(tmp_path),
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--result-output",
            "existing.json",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "result output already exists" in result.output


def test_workflow_run_result_output_rejects_workspace_escape(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "workflow-run",
            "memory",
            "--workspace",
            str(tmp_path),
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--result-output",
            "../outside.json",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "escapes workspace" in result.output


def test_workflow_run_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["workflow-run", "memory", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "workflow_run"
    assert envelope["data"]["schema"] == "agentx.workflow_run.v1"


def test_workflow_run_fail_on_blocker_exits_nonzero() -> None:
    result = CliRunner().invoke(app, ["workflow-run", "memory", "--json", "--fail-on-blocker"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["blockers"] == ["missing_inputs"]


def test_workflow_run_cli_allow_yellow_requires_reason() -> None:
    result = CliRunner().invoke(
        app,
        [
            "workflow-run",
            "memory",
            "--input",
            "完成與待辦=完成 AMH 交接",
            "--execute",
            "--allow-yellow-gates",
            "--json",
            "--fail-on-blocker",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["stopped_at"] == {"reason": "approval_reason_required"}


def test_workflows_plain_outputs_table() -> None:
    result = CliRunner().invoke(app, ["workflows"])

    assert result.exit_code == 0, result.output
    assert "agentX workflows" in result.output
    assert "Headless bundle" in result.output
