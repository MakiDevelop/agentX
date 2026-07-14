import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, traces_payload
from agentx.config import Settings


def _write_trace_session(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                '{"ts":"2026-01-02T00:00:00","event":"session_start","model":"gemma4:31b","namespace":"project:test"}',
                '{"ts":"2026-01-02T00:00:01","event":"user","mode":"agent","content":"hello"}',
                '{"ts":"2026-01-02T00:00:02","event":"tool","command":"/git","ok":true,"content":"## main"}',
                '{"ts":"2026-01-02T00:00:03","event":"tool","command":"/test","ok":false,"content":"failed"}',
                '{"ts":"2026-01-02T00:00:04","event":"approval","tool":"apply_patch","risk":"YELLOW","allowed":false,"source":"manual_denied"}',
                '{"ts":"2026-01-02T00:00:05","event":"assistant","mode":"agent","content":"done"}',
                "not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_traces_payload_summarizes_transcript(tmp_path: Path) -> None:
    session = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    _write_trace_session(session)

    payload = traces_payload(Settings(workspace=tmp_path), session="20260102-000000", limit=3)

    assert payload["schema"] == "agentx.traces.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["session"] == "20260102-000000"
    assert payload["ok"] is True
    assert payload["path"] == str(session)
    assert payload["count"] == 6
    assert payload["invalid_line_count"] == 1
    assert payload["event_counts"]["tool"] == 2  # type: ignore[index]
    assert payload["tool_counts"]["/git"] == 1  # type: ignore[index]
    assert payload["tool_counts"]["/test"] == 1  # type: ignore[index]
    assert payload["approval_count"] == 1
    assert payload["approval_denied_count"] == 1
    assert payload["tool_failure_count"] == 1
    assert payload["error_like_count"] == 2
    assert payload["first_ts"] == "2026-01-02T00:00:00"
    assert payload["last_ts"] == "2026-01-02T00:00:05"
    assert len(payload["recent_events"]) == 3
    assert payload["recent_events"][0]["event"] == "tool"  # type: ignore[index]


def test_traces_payload_handles_missing_session(tmp_path: Path) -> None:
    payload = traces_payload(Settings(workspace=tmp_path), session="missing")

    assert payload["ok"] is False
    assert payload["path"] is None
    assert payload["count"] == 0
    assert payload["event_counts"] == {}
    assert payload["recent_events"] == []
    assert payload["detail"] == "transcript not found: missing"


def test_traces_payload_derives_events_from_session_store_metadata(tmp_path: Path) -> None:
    session = tmp_path / ".agentx" / "sessions" / "run.session.jsonl"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(
        "\n".join(
            [
                '{"id":"000000","ts":"2026-01-02T00:00:00","role":"system","content":"session_start","metadata":{"event":"session_start","model":"gemma4:31b"}}',
                '{"id":"000001","ts":"2026-01-02T00:00:01","role":"user","content":"hello"}',
                '{"id":"000002","ts":"2026-01-02T00:00:02","role":"system","content":"[state:tool_outcomes]","metadata":{"event":"state","name":"tool_outcomes","data":{}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = traces_payload(Settings(workspace=tmp_path), session="run.session", limit=3)

    assert payload["event_counts"]["session_start"] == 1  # type: ignore[index]
    assert payload["event_counts"]["state"] == 1  # type: ignore[index]
    assert payload["event_counts"]["role:user"] == 1  # type: ignore[index]
    assert payload["recent_events"][0]["event"] == "session_start"  # type: ignore[index]


def test_traces_json_outputs_summary(tmp_path: Path) -> None:
    _write_trace_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(app, ["traces", "20260102-000000", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.traces.v1"
    assert payload["event_counts"]["tool"] == 2
    assert payload["approval_denied_count"] == 1


def test_traces_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _write_trace_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(
        app,
        ["traces", "20260102-000000", "--workspace", str(tmp_path), "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "traces"
    assert envelope["data"]["schema"] == "agentx.traces.v1"


def test_traces_plain_outputs_table(tmp_path: Path) -> None:
    _write_trace_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(app, ["traces", "20260102-000000", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX trace summary" in result.output
    assert "approval_denied_count" in result.output
    assert "tool_failure_count" in result.output
