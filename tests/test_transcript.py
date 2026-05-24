from pathlib import Path

from agentx.transcript import find_transcript, list_transcripts, transcript_overview


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
    assert "assistant" in str(overview["last"])
