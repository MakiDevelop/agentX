import json

from typer.testing import CliRunner

from agentx.cli import app, workflow_catalog_payload


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
    assert "Approval audit" in workflows
    assert "audit" in workflows["Approval audit"]["aliases"]
    assert workflows["小步修改"]["steps"][2] == {"command": "讓 agent 讀檔與改檔", "runnable": False}
    assert "讓 agent 讀檔與改檔" not in workflows["小步修改"]["commands"]


def test_workflow_catalog_payload_filters_by_alias() -> None:
    payload = workflow_catalog_payload("headless")

    assert payload["query"] == "headless"
    assert payload["count"] == 1
    assert payload["workflows"][0]["goal"] == "Headless bundle"
    assert "--artifact-dir" in payload["workflows"][0]["path"]
    assert payload["workflows"][0]["commands"][0].startswith("agentx -p")


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


def test_workflows_plain_outputs_table() -> None:
    result = CliRunner().invoke(app, ["workflows"])

    assert result.exit_code == 0, result.output
    assert "agentX workflows" in result.output
    assert "Headless bundle" in result.output
