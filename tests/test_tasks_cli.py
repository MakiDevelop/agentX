import json

from typer.testing import CliRunner

from agentx.cli import app, tasks_payload
from agentx.config import Settings
from agentx.tasks import save_tasks


def _write_tasks(workspace) -> None:  # noqa: ANN001
    save_tasks(
        workspace,
        [
            {"id": 1, "description": "active work", "status": "in_progress", "notes": "doing"},
            {"id": 2, "description": "next work", "status": "pending", "notes": ""},
            {"id": 3, "description": "finished work", "status": "done", "notes": "verified"},
            {"id": 4, "description": "blocked work", "status": "blocked", "notes": "needs input"},
        ],
    )


def test_tasks_payload_returns_complete_task_list(tmp_path) -> None:  # noqa: ANN001
    _write_tasks(tmp_path)

    payload = tasks_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.tasks.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["status_filter"] == "all"
    assert payload["count"] == 4
    assert payload["total_count"] == 4
    assert payload["by_status"] == {
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "blocked": 1,
    }
    assert payload["tasks"][0]["description"] == "active work"  # type: ignore[index]
    assert "【目前任務清單摘要】" in payload["summary"]


def test_tasks_payload_filters_active_tasks(tmp_path) -> None:  # noqa: ANN001
    _write_tasks(tmp_path)

    payload = tasks_payload(Settings(workspace=tmp_path), status_filter="active")

    assert payload["status_filter"] == "active"
    assert payload["count"] == 3
    assert [task["status"] for task in payload["tasks"]] == [  # type: ignore[index]
        "in_progress",
        "pending",
        "blocked",
    ]


def test_tasks_json_outputs_filtered_tasks(tmp_path) -> None:  # noqa: ANN001
    _write_tasks(tmp_path)

    result = CliRunner().invoke(app, ["tasks", "blocked", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.tasks.v1"
    assert payload["status_filter"] == "blocked"
    assert payload["count"] == 1
    assert payload["total_count"] == 4
    assert payload["tasks"][0]["description"] == "blocked work"
    assert payload["tasks"][0]["notes"] == "needs input"


def test_tasks_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    _write_tasks(tmp_path)

    result = CliRunner().invoke(app, ["tasks", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "tasks"
    assert envelope["data"]["schema"] == "agentx.tasks.v1"
    assert envelope["data"]["count"] == 4


def test_tasks_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    _write_tasks(tmp_path)

    result = CliRunner().invoke(app, ["tasks", "active", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX tasks" in result.output
    assert "active work" in result.output
    assert "blocked work" in result.output
    assert "finished work" not in result.output
    assert "count=3 total=4" in result.output


def test_tasks_rejects_unknown_status(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["tasks", "weird", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code != 0
    assert "status must be one of" in result.output
