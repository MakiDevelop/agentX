import json

from typer.testing import CliRunner

from agentx.cli import app
from agentx.command_catalog import COMMAND_PARITY_MATRIX, command_parity_payload


def test_command_parity_payload_lists_runner_and_slash_mappings() -> None:
    payload = command_parity_payload()

    assert payload["schema"] == "agentx.command_parity.v1"
    assert payload["query"] == ""
    assert payload["count"] == len(COMMAND_PARITY_MATRIX)
    domains = payload["by_domain"]
    assert set(domains) == {"memory", "ace", "artifacts", "next", "gate", "command-plan"}
    assert domains["memory"]["status"] == "mapped"
    assert "/memory QUERY" in domains["memory"]["slash_commands"]
    assert "agentx memory-status --json" in domains["memory"]["runner_commands"]
    assert "agentx.memory_write.v1" in domains["memory"]["schemas"]
    assert "memory_write" in domains["memory"]["jsonl_events"]
    assert domains["ace"]["status"] == "runner_only_workflow"
    assert "/workflow ace" in domains["ace"]["slash_commands"]
    assert "agentx ace-status SESSION --json" in domains["ace"]["runner_commands"]
    assert "agentx.ace_status.v1" in domains["ace"]["schemas"]
    assert domains["gate"]["status"] == "mapped"
    assert "/commit [MESSAGE]" in domains["gate"]["slash_commands"]
    assert "agentx gate --json" in domains["gate"]["runner_commands"]
    assert "agentx.gate.v1" in domains["gate"]["schemas"]


def test_command_parity_payload_filters_by_domain_or_schema() -> None:
    memory_payload = command_parity_payload("memory")
    ace_schema_payload = command_parity_payload("agentx.ace_answer.v1")
    runner_payload = command_parity_payload("command-plan")

    assert memory_payload["count"] == 1
    assert memory_payload["entries"][0]["domain"] == "memory"
    assert ace_schema_payload["count"] == 1
    assert ace_schema_payload["entries"][0]["domain"] == "ace"
    assert runner_payload["count"] == 1
    assert runner_payload["entries"][0]["domain"] == "command-plan"


def test_command_parity_json_outputs_payload() -> None:
    result = CliRunner().invoke(app, ["command-parity", "gate", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.command_parity.v1"
    assert payload["count"] == 1
    assert payload["entries"][0]["domain"] == "gate"


def test_command_parity_jsonl_outputs_event_envelope() -> None:
    result = CliRunner().invoke(app, ["command-parity", "ace", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "command_parity"
    assert envelope["data"]["schema"] == "agentx.command_parity.v1"
    assert envelope["data"]["entries"][0]["domain"] == "ace"


def test_command_parity_plain_outputs_table() -> None:
    result = CliRunner().invoke(app, ["command-parity", "memory"])

    assert result.exit_code == 0, result.output
    assert "agentX command parity: memory" in result.output
    assert "agentx memory-status --json" in result.output
