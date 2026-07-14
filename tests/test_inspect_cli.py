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
    (tmp_path / "tracked.py").write_text("print('one')\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.py").write_text("print('one')\nprint('two')\n", encoding="utf-8")
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
    assert payload["traces"]["schema"] == "agentx.traces.v1"  # type: ignore[index]
    assert payload["traces"]["event_counts"]["approval"] == 1  # type: ignore[index]
    assert payload["diff"]["schema"] == "agentx.diff.v1"  # type: ignore[index]
    assert payload["diff"]["file_count"] >= 1  # type: ignore[index]
    diff_paths = {item["path"] for item in payload["diff"]["files"]}  # type: ignore[index]
    assert "tracked.py" in diff_paths
    assert payload["capabilities"]["schema"] == "agentx.capabilities.v1"  # type: ignore[index]
    assert payload["verify_commands"] == [
        {"command": "uv run ruff check .", "argv": ["uv", "run", "ruff", "check", "."]},
        {"command": "uv run pytest -q", "argv": ["uv", "run", "pytest", "-q"]},
    ]
    assert "agentx diff --json" in payload["next_commands"]
    assert "agentx gate --json --fail-on-blocker" in payload["next_commands"]
    assert "agentx review --json --fail-on-blocker" in payload["next_commands"]
    assert "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker" in payload["next_commands"]
    assert "secret-token" not in json.dumps(payload)


def test_inspect_json_outputs_payload(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["inspect", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.inspect.v1"
    assert payload["status"]["git"]["ok"] is True
    assert payload["diff"]["schema"] == "agentx.diff.v1"
    assert payload["verify_commands"][0]["command"] == "uv run ruff check ."
    assert payload["next_commands"][0] == "agentx diff --json"
    assert "agentx gate --json --fail-on-blocker" in payload["next_commands"]
    assert "agentx review --json --fail-on-blocker" in payload["next_commands"]
    assert "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker" in payload["next_commands"]
    assert "agentx verify --json --fail-on-error" in payload["next_commands"]
    assert "agentx traces latest --json" in payload["next_commands"]


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
    assert "diff" in result.output
    assert "verify_commands" in result.output
