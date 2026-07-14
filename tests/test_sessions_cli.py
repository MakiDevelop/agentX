import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, sessions_payload
from agentx.config import Settings


def _write_session(path: Path, *, model: str = "gemma4:31b", namespace: str = "project:test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f'{{"ts":"2026-01-02T00:00:00","event":"session_start","model":"{model}","namespace":"{namespace}"}}',
                '{"ts":"2026-01-02T00:00:01","event":"user","content":"hello"}',
                '{"ts":"2026-01-02T00:00:02","event":"approval","tool":"memory_write","risk":"YELLOW","allowed":false}',
                '{"ts":"2026-01-02T00:00:03","event":"assistant","content":"done"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_sessions_payload_lists_transcript_overviews(tmp_path) -> None:  # noqa: ANN001
    _write_session(tmp_path / ".agentx" / "sessions" / "20260101-000000.jsonl")
    _write_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl", model="qwen3:8b")

    payload = sessions_payload(Settings(workspace=tmp_path), limit=1)

    assert payload["schema"] == "agentx.sessions.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["count"] == 1
    assert payload["sessions"][0]["name"] == "20260102-000000"
    assert payload["sessions"][0]["model"] == "qwen3:8b"
    assert payload["sessions"][0]["approval_denied_count"] == 1


def test_sessions_json_outputs_saved_sessions(tmp_path) -> None:  # noqa: ANN001
    _write_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(app, ["sessions", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.sessions.v1"
    assert payload["count"] == 1
    assert payload["sessions"][0]["namespace"] == "project:test"
    assert payload["sessions"][0]["turns"] == 2


def test_sessions_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    _write_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(app, ["sessions", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "sessions"
    assert envelope["data"]["schema"] == "agentx.sessions.v1"


def test_sessions_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    _write_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(app, ["sessions", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX sessions" in result.output
    assert "Model" in result.output
    assert "Approval" in result.output
