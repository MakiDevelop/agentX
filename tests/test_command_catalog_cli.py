import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import COMMAND_CATALOG, command_catalog_payload, filtered_command_catalog_payload


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


def test_command_catalog_payload_filters_by_command_prefix() -> None:
    payload = filtered_command_catalog_payload("/workflow")

    assert payload["query"] == "/workflow"
    assert payload["count"] == 2
    assert [command["usage"] for command in payload["commands"]] == ["/workflows", "/workflow NAME"]


def test_command_catalog_payload_filters_by_keyword() -> None:
    payload = filtered_command_catalog_payload("memory")

    assert payload["query"] == "memory"
    assert payload["count"] > 0
    assert any(command["command"] == "/handoff" for command in payload["commands"])
    assert all(
        "memory" in " ".join(
            [
                command["command"],
                command["usage"],
                command["description"],
                *command["examples"],
                *command["related"],
                command["risk"],
            ]
        ).lower()
        for command in payload["commands"]
    )


def test_commands_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["commands", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "commands"
    assert envelope["data"]["schema"] == "agentx.command_catalog.v1"


def test_commands_json_accepts_query_filter() -> None:
    result = CliRunner().invoke(app, ["commands", "/workflow", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "/workflow"
    assert [command["usage"] for command in payload["commands"]] == ["/workflows", "/workflow NAME"]


def test_commands_json_no_matches_is_empty_catalog() -> None:
    result = CliRunner().invoke(app, ["commands", "definitely-not-a-command", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "definitely-not-a-command"
    assert payload["count"] == 0
    assert payload["commands"] == []


def test_commands_plain_outputs_human_catalog() -> None:
    result = CliRunner().invoke(app, ["commands"])

    assert result.exit_code == 0, result.output
    assert "agentX command catalog" in result.output
    assert "/workflow" in result.output


def test_commands_plain_accepts_query_filter() -> None:
    result = CliRunner().invoke(app, ["commands", "approval"])

    assert result.exit_code == 0, result.output
    assert "agentX command catalog: approval" in result.output
    assert "/approval" in result.output
