from pathlib import Path

from agentx.transcript import (
    find_transcript,
    list_transcripts,
    resume_loaded_message,
    transcript_overview,
)


def test_list_transcripts_returns_newest_first(tmp_path: Path) -> None:
    sessions = tmp_path / ".agentx" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "20260101-000000.jsonl").write_text("", encoding="utf-8")
    (sessions / "20260102-000000.jsonl").write_text("", encoding="utf-8")

    paths = list_transcripts(tmp_path)

    assert [path.name for path in paths] == ["20260102-000000.jsonl", "20260101-000000.jsonl"]


def test_find_latest_transcript_can_exclude_current_session(tmp_path: Path) -> None:
    sessions = tmp_path / ".agentx" / "sessions"
    sessions.mkdir(parents=True)
    previous = sessions / "20260101-000000.jsonl"
    current = sessions / "20260102-000000.jsonl"
    previous.write_text("", encoding="utf-8")
    current.write_text("", encoding="utf-8")

    assert find_transcript(tmp_path, "latest", exclude=current) == previous


def test_transcript_overview_returns_session_metadata(tmp_path: Path) -> None:
    session = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "\n".join([
            '{"ts":"2026-01-02T00:00:00","event":"session_start","model":"gemma4:31b","namespace":"project:agentX"}',
            '{"ts":"2026-01-02T00:00:01","event":"user","content":"請看 README"}',
            '{"ts":"2026-01-02T00:00:02","event":"assistant","content":"已整理重點"}',
        ]) + "\n",
        encoding="utf-8",
    )

    overview = transcript_overview(session)

    assert overview["name"] == "20260102-000000"
    assert overview["started"] == "2026-01-02T00:00:00"
    assert overview["model"] == "gemma4:31b"
    assert overview["namespace"] == "project:agentX"
    assert overview["turns"] == 2
    assert overview["approval_count"] == 0
    assert overview["approval_denied_count"] == 0
    assert overview["approval"] == "-"
    assert "assistant" in str(overview["last"])


def test_transcript_overview_counts_approval_receipts(tmp_path: Path) -> None:
    session = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "\n".join([
            '{"ts":"2026-01-02T00:00:00","event":"session_start","model":"gemma4:31b","namespace":"project:agentX"}',
            '{"ts":"2026-01-02T00:00:01","event":"approval","tool":"memory_write","risk":"YELLOW","source":"auto_approved","allowed":true}',
            '{"ts":"2026-01-02T00:00:02","event":"approval","tool":"apply_patch","risk":"YELLOW","source":"manual_denied","allowed":false}',
            '{"ts":"2026-01-02T00:00:03","event":"assistant","content":"done"}',
        ]) + "\n",
        encoding="utf-8",
    )

    overview = transcript_overview(session)

    assert overview["approval_count"] == 2
    assert overview["approval_denied_count"] == 1
    assert overview["approval"] == "2/1 denied"
    assert "assistant" in str(overview["last"])


def test_resume_loaded_message_includes_source_and_size(tmp_path: Path) -> None:
    path = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    summary = "Resumed transcript: demo\n- user: hello\n- assistant: hi"

    message = resume_loaded_message(path, summary)

    assert "resumed 20260102-000000" in message
    assert f"source: {path}" in message
    assert "loaded summary: 3 lines" in message
    assert "/context" in message
