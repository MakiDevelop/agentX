import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import CLI_CAPABILITIES, RUNNER_RECOMMENDED_ENTRYPOINTS, capabilities_payload


def test_capabilities_payload_lists_top_level_cli_commands() -> None:
    payload = capabilities_payload()

    assert payload["schema"] == "agentx.capabilities.v1"
    assert payload["query"] == ""
    assert payload["count"] == len(CLI_CAPABILITIES)
    assert payload["recommended_entrypoints"] == RUNNER_RECOMMENDED_ENTRYPOINTS
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
