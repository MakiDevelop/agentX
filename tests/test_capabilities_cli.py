import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import CLI_CAPABILITIES, capabilities_payload


def test_capabilities_payload_lists_top_level_cli_commands() -> None:
    payload = capabilities_payload()

    assert payload["schema"] == "agentx.capabilities.v1"
    assert payload["query"] == ""
    assert payload["count"] == len(CLI_CAPABILITIES)
    commands = {item["command"]: item for item in payload["capabilities"]}  # type: ignore[index]
    assert "agentx verify" in commands
    assert commands["agentx verify"]["schemas"] == ["agentx.verify.v1"]
    assert commands["agentx approvals"]["jsonl_event"] == "approvals"
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

    assert schema_payload["count"] == 1
    assert schema_payload["capabilities"][0]["command"] == "agentx tasks"  # type: ignore[index]
    assert keyword_payload["count"] == 1
    assert keyword_payload["capabilities"][0]["command"] == "agentx approvals"  # type: ignore[index]


def test_capabilities_json_outputs_catalog() -> None:
    result = CliRunner().invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.capabilities.v1"
    assert payload["count"] == len(CLI_CAPABILITIES)
    assert any(item["command"] == "agentx verify" for item in payload["capabilities"])


def test_capabilities_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["capabilities", "verify", "--output-format", "jsonl"])

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
