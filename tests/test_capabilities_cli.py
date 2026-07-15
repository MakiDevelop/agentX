import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import CLI_CAPABILITIES, RUNNER_RECOMMENDED_ENTRYPOINTS, RUNNER_SMOKE_WORKFLOWS, capabilities_payload


def test_capabilities_payload_lists_top_level_cli_commands() -> None:
    payload = capabilities_payload()

    assert payload["schema"] == "agentx.capabilities.v1"
    assert payload["query"] == ""
    assert payload["count"] == len(CLI_CAPABILITIES)
    assert payload["recommended_entrypoints"] == RUNNER_RECOMMENDED_ENTRYPOINTS
    assert payload["runner_smokes"] == RUNNER_SMOKE_WORKFLOWS
    entrypoints = {item["name"]: item for item in payload["recommended_entrypoints"]}  # type: ignore[index]
    smokes = {item["name"]: item for item in payload["runner_smokes"]}  # type: ignore[index]
    assert entrypoints["infra_preflight"] == {
        "name": "infra_preflight",
        "command": "agentx infra resource-bundle --json",
        "schema": "agentx.infrastructure_context.v1",
        "reason": "load read-only resource, home AI facilities, and VPS routing context before SSH, deploy, or cross-machine work",
    }
    assert entrypoints["memory_handoff"] == {
        "name": "memory_handoff",
        "command": "agentx workflows memory --json",
        "schema": "agentx.workflow_catalog.v1",
        "reason": "discover the AMH read, dry-run write, and explicit write handoff sequence",
    }
    assert entrypoints["ace_council"] == {
        "name": "ace_council",
        "command": "agentx workflows ace --json",
        "schema": "agentx.workflow_catalog.v1",
        "reason": "discover the ACE manifest, briefing, answer, and status workflow for multi-agent coordination",
    }
    assert smokes["amh_memory_workflow_chain"]["workflow"] == "memory"
    assert smokes["amh_memory_workflow_chain"]["expected_chain_status"] == "ready"
    assert "does not write AMH" in smokes["amh_memory_workflow_chain"]["risk"]
    assert smokes["ace_council_workflow_chain"]["workflow"] == "ace"
    assert smokes["ace_council_workflow_chain"]["expected_chain_status"] == "ready"
    assert "does not create ACE files" in smokes["ace_council_workflow_chain"]["risk"]
    commands = {item["command"]: item for item in payload["capabilities"]}  # type: ignore[index]
    assert "agentx verify" in commands
    assert "agentx artifacts" in commands
    assert "agentx handoff-inspect" in commands
    assert "agentx handoff-resume" in commands
    assert "agentx traces" in commands
    assert "agentx diff" in commands
    assert "agentx patch-check" in commands
    assert "agentx command-plan" in commands
    assert "agentx review" in commands
    assert "agentx commit-plan" in commands
    assert "agentx gate" in commands
    assert "agentx next" in commands
    assert "agentx tool-plan" in commands
    assert "agentx infra" in commands
    assert "agentx memory-status" in commands
    assert "agentx memory-read" in commands
    assert "agentx memory-write" in commands
    assert "agentx workflow-plan" in commands
    assert "agentx workflow-run" in commands
    assert "agentx instructions" in commands
    assert "agentx command-parity" in commands
    assert commands["agentx verify"]["schemas"] == ["agentx.verify.v1"]
    assert commands["agentx artifacts"]["schemas"] == ["agentx.artifacts.v1"]
    assert commands["agentx handoff-inspect"]["jsonl_event"] == "handoff_inspect"
    assert commands["agentx handoff-resume"]["jsonl_event"] == "handoff_resume"
    assert commands["agentx handoff-resume"]["schemas"] == []
    assert commands["agentx traces"]["schemas"] == ["agentx.traces.v1"]
    assert commands["agentx diff"]["schemas"] == ["agentx.diff.v1"]
    assert commands["agentx patch-check"]["schemas"] == ["agentx.patch_check.v1"]
    assert commands["agentx patch-check"]["jsonl_event"] == "patch_check"
    assert commands["agentx command-plan"]["schemas"] == ["agentx.command_plan.v1"]
    assert commands["agentx command-plan"]["jsonl_event"] == "command_plan"
    assert commands["agentx review"]["schemas"] == ["agentx.review.v1"]
    assert commands["agentx commit-plan"]["schemas"] == ["agentx.commit_plan.v1"]
    assert commands["agentx gate"]["schemas"] == ["agentx.gate.v1"]
    assert commands["agentx gate"]["jsonl_event"] == "gate"
    assert commands["agentx next"]["schemas"] == ["agentx.next.v1"]
    assert commands["agentx next"]["jsonl_event"] == "next"
    assert commands["agentx tool-plan"]["schemas"] == ["agentx.tool_plan.v1"]
    assert commands["agentx tool-plan"]["jsonl_event"] == "tool_plan"
    assert commands["agentx infra"]["schemas"] == ["agentx.infrastructure_context.v1"]
    assert commands["agentx infra"]["jsonl_event"] == "infra"
    assert commands["agentx memory-status"]["schemas"] == ["agentx.memory_status.v1"]
    assert commands["agentx memory-status"]["jsonl_event"] == "memory_status"
    assert commands["agentx memory-read"]["schemas"] == ["agentx.memory_read.v1"]
    assert commands["agentx memory-read"]["jsonl_event"] == "memory_read"
    assert commands["agentx memory-write"]["schemas"] == ["agentx.memory_write.v1"]
    assert commands["agentx memory-write"]["jsonl_event"] == "memory_write"
    assert commands["agentx command-parity"]["schemas"] == ["agentx.command_parity.v1"]
    assert commands["agentx command-parity"]["jsonl_event"] == "command_parity"
    assert commands["agentx workflow-plan"]["schemas"] == ["agentx.workflow_plan.v1"]
    assert commands["agentx workflow-plan"]["jsonl_event"] == "workflow_plan"
    assert commands["agentx workflow-run"]["schemas"] == ["agentx.workflow_run.v1"]
    assert commands["agentx workflow-run"]["jsonl_event"] == "workflow_run"
    assert commands["agentx instructions"]["schemas"] == ["agentx.local_instructions.v1"]
    assert commands["agentx instructions"]["jsonl_event"] == "instructions"
    assert commands["agentx approvals"]["jsonl_event"] == "approvals"
    assert payload["by_schema"]["agentx.inspect.v1"] == {  # type: ignore[index]
        "command": "agentx inspect",
        "jsonl_event": "inspect",
        "usage": "agentx inspect --json",
    }
    assert payload["by_schema"]["agentx.gate.v1"]["command"] == "agentx gate"  # type: ignore[index]
    assert all(
        set(item) == {
            "command",
            "usage",
            "description",
            "examples",
            "schemas",
            "jsonl_event",
            "risk",
        }
        for item in payload["capabilities"]  # type: ignore[index]
    )


def test_capabilities_payload_filters_by_schema_or_keyword() -> None:
    schema_payload = capabilities_payload("agentx.tasks.v1")
    keyword_payload = capabilities_payload("denied")
    diff_payload = capabilities_payload("agentx.diff.v1")
    patch_check_payload = capabilities_payload("agentx.patch_check.v1")
    command_plan_payload = capabilities_payload("agentx.command_plan.v1")
    review_payload = capabilities_payload("agentx.review.v1")
    commit_plan_payload = capabilities_payload("agentx.commit_plan.v1")
    gate_payload = capabilities_payload("agentx.gate.v1")
    next_payload = capabilities_payload("agentx.next.v1")
    tool_plan_payload = capabilities_payload("agentx.tool_plan.v1")
    infra_payload = capabilities_payload("agentx.infrastructure_context.v1")
    memory_status_payload = capabilities_payload("agentx.memory_status.v1")
    memory_read_payload = capabilities_payload("agentx.memory_read.v1")
    memory_write_payload = capabilities_payload("agentx.memory_write.v1")
    workflow_plan_payload = capabilities_payload("agentx.workflow_plan.v1")
    workflow_run_payload = capabilities_payload("agentx.workflow_run.v1")
    instructions_payload = capabilities_payload("agentx.local_instructions.v1")
    command_parity_payload = capabilities_payload("agentx.command_parity.v1")

    assert schema_payload["count"] == 1
    assert schema_payload["capabilities"][0]["command"] == "agentx tasks"  # type: ignore[index]
    assert set(schema_payload["by_schema"]) == {"agentx.tasks.v1"}  # type: ignore[arg-type]
    assert keyword_payload["count"] == 1
    assert keyword_payload["capabilities"][0]["command"] == "agentx approvals"  # type: ignore[index]
    assert diff_payload["count"] == 1
    assert diff_payload["capabilities"][0]["command"] == "agentx diff"  # type: ignore[index]
    assert patch_check_payload["count"] == 1
    assert patch_check_payload["capabilities"][0]["command"] == "agentx patch-check"  # type: ignore[index]
    assert command_plan_payload["count"] == 1
    assert command_plan_payload["capabilities"][0]["command"] == "agentx command-plan"  # type: ignore[index]
    assert review_payload["count"] == 1
    assert review_payload["capabilities"][0]["command"] == "agentx review"  # type: ignore[index]
    assert commit_plan_payload["count"] == 1
    assert commit_plan_payload["capabilities"][0]["command"] == "agentx commit-plan"  # type: ignore[index]
    assert gate_payload["count"] == 1
    assert gate_payload["capabilities"][0]["command"] == "agentx gate"  # type: ignore[index]
    assert next_payload["count"] == 1
    assert next_payload["capabilities"][0]["command"] == "agentx next"  # type: ignore[index]
    assert tool_plan_payload["count"] == 1
    assert tool_plan_payload["capabilities"][0]["command"] == "agentx tool-plan"  # type: ignore[index]
    assert infra_payload["count"] == 1
    assert infra_payload["capabilities"][0]["command"] == "agentx infra"  # type: ignore[index]
    assert memory_status_payload["count"] == 1
    assert memory_status_payload["capabilities"][0]["command"] == "agentx memory-status"  # type: ignore[index]
    assert memory_read_payload["count"] == 1
    assert memory_read_payload["capabilities"][0]["command"] == "agentx memory-read"  # type: ignore[index]
    assert memory_write_payload["count"] == 1
    assert memory_write_payload["capabilities"][0]["command"] == "agentx memory-write"  # type: ignore[index]
    assert workflow_plan_payload["count"] == 1
    assert workflow_plan_payload["capabilities"][0]["command"] == "agentx workflow-plan"  # type: ignore[index]
    assert workflow_run_payload["count"] == 1
    assert workflow_run_payload["capabilities"][0]["command"] == "agentx workflow-run"  # type: ignore[index]
    assert instructions_payload["count"] == 1
    assert instructions_payload["capabilities"][0]["command"] == "agentx instructions"  # type: ignore[index]
    assert command_parity_payload["count"] == 1
    assert command_parity_payload["capabilities"][0]["command"] == "agentx command-parity"  # type: ignore[index]


def test_capabilities_json_outputs_catalog() -> None:
    result = CliRunner().invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.capabilities.v1"
    assert payload["count"] == len(CLI_CAPABILITIES)
    assert any(item["command"] == "agentx verify" for item in payload["capabilities"])


def test_capabilities_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["capabilities", "agentx.verify.v1", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "capabilities"
    assert envelope["data"]["schema"] == "agentx.capabilities.v1"
    assert envelope["data"]["count"] == 1
    assert envelope["data"]["capabilities"][0]["command"] == "agentx verify"


def test_capabilities_plain_outputs_table() -> None:
    result = CliRunner().invoke(app, ["capabilities", "tasks"])

    assert result.exit_code == 0, result.output
    assert "agentX capabilities: tasks" in result.output
    assert "agentx tasks" in result.output
    assert "agentx.tasks.v1" in result.output
