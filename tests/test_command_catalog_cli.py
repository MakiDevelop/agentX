import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import COMMAND_CATALOG, command_catalog_payload


def test_command_catalog_payload_is_machine_readable() -> None:
    payload = command_catalog_payload()

    assert payload["schema"] == "agentx.command_catalog.v1"
    assert payload["count"] == len(COMMAND_CATALOG)
    commands = payload["commands"]
    assert isinstance(commands, list)
    assert any(command["command"] == "/workflow" for command in commands)
    assert all(
        set(command) == {"command", "usage", "description", "examples", "related", "risk"}
        for command in commands
    )


def test_commands_json_outputs_catalog() -> None:
    result = CliRunner().invoke(app, ["commands", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.command_catalog.v1"
    assert payload["count"] == len(COMMAND_CATALOG)
    assert any(command["command"] == "/infra" for command in payload["commands"])


def test_commands_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["commands", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "commands"
    assert envelope["data"]["schema"] == "agentx.command_catalog.v1"


def test_commands_plain_outputs_human_catalog() -> None:
    result = CliRunner().invoke(app, ["commands"])

    assert result.exit_code == 0, result.output
    assert "agentX command catalog" in result.output
    assert "/workflow" in result.output
