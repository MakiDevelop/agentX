import json

from typer.testing import CliRunner

from agentx.cli import app, tool_catalog_payload
from agentx.memory_hall import NullMemoryClient
from agentx.tools import ToolRegistry, builtin_tools


def test_tool_catalog_payload_includes_risk_metadata(tmp_path) -> None:  # noqa: ANN001
    registry = ToolRegistry(builtin_tools(tmp_path, NullMemoryClient()))
    payload = tool_catalog_payload(registry)

    assert payload["schema"] == "agentx.tool_catalog.v1"
    assert payload["count"] == len(payload["tools"])
    assert payload["by_risk"]["GREEN"] > 0
    assert payload["by_risk"]["YELLOW"] > 0
    read_file = next(tool for tool in payload["tools"] if tool["name"] == "read_file")
    assert read_file["risk"] == "GREEN"
    assert "path" in read_file["signature"]


def test_tools_json_outputs_tool_catalog(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["tools", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.tool_catalog.v1"
    assert any(tool["name"] == "read_file" for tool in payload["tools"])
    assert any(tool["risk"] == "YELLOW" for tool in payload["tools"])


def test_tools_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["tools", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "tools"
    assert envelope["data"]["schema"] == "agentx.tool_catalog.v1"


def test_tools_plain_outputs_grouped_table(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["tools", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "GREEN" in result.output
    assert "YELLOW" in result.output
    assert "read_file" in result.output
