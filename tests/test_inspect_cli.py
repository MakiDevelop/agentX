import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, inspect_payload
from agentx.config import Settings
from agentx.tasks import save_tasks


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def _write_session(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                '{"ts":"2026-01-02T00:00:00","event":"session_start","model":"gemma4:31b","namespace":"project:test"}',
                '{"ts":"2026-01-02T00:00:01","event":"approval","tool":"apply_patch","risk":"YELLOW","approval_mode":"ask","source":"manual_denied","allowed":false}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_inspect_payload_aggregates_runner_preflight(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTX_MEMORY_HALL_TOKEN", "secret-token")
    _git_init(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    save_tasks(tmp_path, [{"id": 1, "description": "active work", "status": "in_progress", "notes": ""}])
    _write_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    payload = inspect_payload(
        Settings(workspace=tmp_path),
        namespace="project:test",
        mode="agent",
        approval="ask",
    )

    assert payload["schema"] == "agentx.inspect.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["live_probes"] is False
    assert payload["status"]["schema"] == "agentx.status.v1"  # type: ignore[index]
    assert payload["tasks"]["schema"] == "agentx.tasks.v1"  # type: ignore[index]
    assert payload["tasks"]["count"] == 1  # type: ignore[index]
    assert payload["sessions"]["schema"] == "agentx.sessions.v1"  # type: ignore[index]
    assert payload["approvals"]["schema"] == "agentx.approvals.v1"  # type: ignore[index]
    assert payload["approvals"]["denied_count"] == 1  # type: ignore[index]
    assert payload["capabilities"]["schema"] == "agentx.capabilities.v1"  # type: ignore[index]
    assert payload["verify_commands"] == [
        {"command": "uv run ruff check .", "argv": ["uv", "run", "ruff", "check", "."]},
        {"command": "uv run pytest -q", "argv": ["uv", "run", "pytest", "-q"]},
    ]
    assert "secret-token" not in json.dumps(payload)


def test_inspect_json_outputs_payload(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["inspect", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.inspect.v1"
    assert payload["status"]["git"]["ok"] is True
    assert payload["verify_commands"][0]["command"] == "uv run ruff check ."
    assert payload["next_commands"][0] == "agentx verify --json --fail-on-error"


def test_inspect_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["inspect", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "inspect"
    assert envelope["data"]["schema"] == "agentx.inspect.v1"
    assert envelope["data"]["live_probes"] is False


def test_inspect_plain_outputs_summary(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["inspect", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX inspect" in result.output
    assert "workspace" in result.output
    assert "verify_commands" in result.output
