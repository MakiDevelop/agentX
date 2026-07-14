import json
import subprocess

from typer.testing import CliRunner

from agentx.cli import app, git_status_payload, status_payload
from agentx.config import Settings
from agentx.tasks import save_tasks


def _git_init(path) -> None:  # noqa: ANN001
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_git_status_payload_reports_dirty_workspace(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)
    (tmp_path / "note.txt").write_text("draft\n", encoding="utf-8")

    payload = git_status_payload(tmp_path)

    assert payload["ok"] is True
    assert payload["branch"] in {"main", "master"}
    assert payload["initial"] is True
    assert payload["dirty"] is True
    assert payload["changes_count"] == 1
    assert payload["changes"] == ["?? note.txt"]


def test_status_payload_combines_config_git_and_tasks(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTX_MEMORY_HALL_TOKEN", "secret-token")
    _git_init(tmp_path)
    save_tasks(
        tmp_path,
        [
            {"id": 1, "description": "active work", "status": "in_progress", "notes": ""},
            {"id": 2, "description": "next work", "status": "pending", "notes": ""},
            {"id": 3, "description": "finished work", "status": "done", "notes": ""},
        ],
    )
    settings = Settings(workspace=tmp_path)

    payload = status_payload(settings, namespace="project:test", mode="agent", approval="ask")

    assert payload["schema"] == "agentx.status.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["runtime"]["namespace"] == "project:test"
    assert payload["runtime"]["mode"] == "agent"
    assert payload["git"]["ok"] is True
    assert payload["tasks"]["count"] == 3
    assert payload["tasks"]["by_status"] == {
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "blocked": 0,
    }
    assert payload["tasks"]["active"][0]["description"] == "active work"
    assert payload["config"]["memory_hall_token"] == "set"
    assert "secret-token" not in json.dumps(payload)


def test_status_json_outputs_workspace_posture(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)

    result = CliRunner().invoke(app, ["status", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.status.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["runtime"]["mode"] == "chat"
    assert payload["git"]["ok"] is True
    assert payload["tasks"]["count"] == 0


def test_status_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["status", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "status"
    assert envelope["data"]["schema"] == "agentx.status.v1"


def test_status_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["status", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX status" in result.output
    assert "workspace" in result.output
    assert "git" in result.output
    assert "tasks" in result.output
