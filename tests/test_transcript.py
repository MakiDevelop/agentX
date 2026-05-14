from pathlib import Path

from agentx.transcript import list_transcripts


def test_list_transcripts_returns_newest_first(tmp_path: Path) -> None:
    sessions = tmp_path / ".agentx" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "20260101-000000.jsonl").write_text("", encoding="utf-8")
    (sessions / "20260102-000000.jsonl").write_text("", encoding="utf-8")

    paths = list_transcripts(tmp_path)

    assert [path.name for path in paths] == ["20260102-000000.jsonl", "20260101-000000.jsonl"]
