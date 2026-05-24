from pathlib import Path

from agentx.transcript import find_transcript, list_transcripts


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
