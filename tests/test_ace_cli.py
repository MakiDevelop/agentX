import json

from typer.testing import CliRunner

from agentx.ace import ace_answer_payload, ace_append_payload, ace_briefing_payload, ace_init_payload
from agentx.cli import app


def test_ace_init_payload_dry_run_does_not_write(tmp_path) -> None:  # noqa: ANN001
    payload = ace_init_payload(
        session_id="2026-07-15-agentx-ace",
        goal="Add ACE support",
        routing_decision="Codex: architect",
        root=tmp_path,
    )

    assert payload["schema"] == "agentx.ace_session.v1"
    assert payload["ok"] is True
    assert payload["write"] is False
    assert payload["warnings"] == ["dry_run_no_files_written"]
    assert "## GOAL" in payload["manifest"]
    assert "Add ACE support" in payload["manifest"]
    assert not (tmp_path / "2026-07-15-agentx-ace" / "_manifest.md").exists()


def test_ace_init_payload_write_creates_manifest(tmp_path) -> None:  # noqa: ANN001
    payload = ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        routing_decision="Gemini: reviewer",
        root=tmp_path,
        write=True,
    )

    manifest = tmp_path / "session-1" / "_manifest.md"
    assert payload["ok"] is True
    assert payload["write"] is True
    assert payload["manifest_exists"] is True
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "# ACE Session: session-1" in text
    assert "## ROUTING DECISIONS" in text
    assert "Gemini: reviewer" in text
    assert "## OPEN QUESTIONS" in text


def test_ace_init_payload_blocks_existing_manifest(tmp_path) -> None:  # noqa: ANN001
    manifest = tmp_path / "session-1" / "_manifest.md"
    manifest.parent.mkdir()
    manifest.write_text("existing", encoding="utf-8")

    payload = ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    assert payload["ok"] is False
    assert payload["blockers"] == ["manifest_already_exists"]
    assert manifest.read_text(encoding="utf-8") == "existing"


def test_ace_init_payload_blocks_bad_session_id(tmp_path) -> None:  # noqa: ANN001
    payload = ace_init_payload(
        session_id="../bad",
        goal="Coordinate agents",
        root=tmp_path,
    )

    assert payload["ok"] is False
    assert "session_id_must_not_contain_path_separators" in payload["blockers"]


def test_ace_init_cli_outputs_jsonl_event(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "ace-init",
            "session-1",
            "--goal",
            "Coordinate agents",
            "--root",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "ace_init"
    assert envelope["data"]["schema"] == "agentx.ace_session.v1"
    assert envelope["data"]["write"] is False


def test_ace_init_cli_write_outputs_json(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "ace-init",
            "session-1",
            "--goal",
            "Coordinate agents",
            "--root",
            str(tmp_path),
            "--write",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.ace_session.v1"
    assert payload["ok"] is True
    assert (tmp_path / "session-1" / "_manifest.md").exists()


def test_ace_append_payload_updates_manifest_section(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    payload = ace_append_payload(
        session_id="session-1",
        section="finding",
        text="Gemini found no blocker",
        root=tmp_path,
        agent="gemini",
    )

    manifest = tmp_path / "session-1" / "_manifest.md"
    text = manifest.read_text(encoding="utf-8")
    assert payload["schema"] == "agentx.ace_append.v1"
    assert payload["ok"] is True
    assert payload["heading"] == "CUMULATIVE FINDINGS"
    assert "[gemini] Gemini found no blocker" in text
    assert text.index("[gemini] Gemini found no blocker") > text.index("## CUMULATIVE FINDINGS")
    assert payload["recommended_command"] == "agentx next --json"


def test_ace_append_cli_outputs_jsonl_event(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-append",
            "session-1",
            "decision",
            "Use append-only manifest updates",
            "--root",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "ace_append"
    assert envelope["data"]["schema"] == "agentx.ace_append.v1"
    assert envelope["data"]["heading"] == "DECISIONS TAKEN"
    assert "Use append-only manifest updates" in envelope["data"]["entry"]


def test_ace_append_blocks_missing_manifest(tmp_path) -> None:  # noqa: ANN001
    payload = ace_append_payload(
        session_id="session-1",
        section="finding",
        text="No manifest yet",
        root=tmp_path,
    )

    assert payload["ok"] is False
    assert payload["blockers"] == ["manifest_not_found"]


def test_ace_append_blocks_unknown_section(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-append",
            "session-1",
            "weird",
            "No valid target",
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["blockers"] == ["unknown_section"]


def test_ace_briefing_payload_dry_run_includes_manifest_snapshot(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )
    ace_append_payload(
        session_id="session-1",
        section="finding",
        text="Gemini found no blocker",
        root=tmp_path,
        agent="gemini",
    )

    payload = ace_briefing_payload(
        session_id="session-1",
        agent="grok",
        role="Implementer",
        task="Implement the accepted decision",
        root=tmp_path,
    )

    assert payload["schema"] == "agentx.ace_briefing.v1"
    assert payload["ok"] is True
    assert payload["write"] is False
    assert payload["warnings"] == ["dry_run_no_files_written"]
    assert "ACE Briefing: grok" in payload["briefing"]
    assert "Role: Implementer" in payload["briefing"]
    assert "Implement the accepted decision" in payload["briefing"]
    assert "Gemini found no blocker" in payload["briefing"]
    assert not (tmp_path / "session-1" / "briefing-grok.md").exists()


def test_ace_briefing_payload_write_creates_default_briefing(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    payload = ace_briefing_payload(
        session_id="session-1",
        agent="gemini",
        role="Reviewer",
        task="Review current findings",
        root=tmp_path,
        write=True,
    )

    briefing = tmp_path / "session-1" / "briefing-gemini.md"
    assert payload["ok"] is True
    assert payload["briefing_exists"] is True
    assert briefing.exists()
    text = briefing.read_text(encoding="utf-8")
    assert "# ACE Briefing: gemini" in text
    assert "Review current findings" in text


def test_ace_briefing_cli_outputs_jsonl_event(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-briefing",
            "session-1",
            "--agent",
            "codex",
            "--role",
            "Architect",
            "--root",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "ace_briefing"
    assert envelope["data"]["schema"] == "agentx.ace_briefing.v1"
    assert envelope["data"]["agent"] == "codex"
    assert envelope["data"]["write"] is False


def test_ace_briefing_blocks_missing_manifest(tmp_path) -> None:  # noqa: ANN001
    payload = ace_briefing_payload(
        session_id="session-1",
        agent="gemini",
        root=tmp_path,
    )

    assert payload["ok"] is False
    assert payload["blockers"] == ["manifest_not_found"]


def test_ace_briefing_blocks_output_path_escape(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-briefing",
            "session-1",
            "--agent",
            "gemini",
            "--output",
            "../bad.md",
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["blockers"] == ["output_must_be_session_relative_filename"]


def test_ace_answer_payload_writes_answer_and_updates_manifest(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    payload = ace_answer_payload(
        session_id="session-1",
        agent="gemini",
        answer="No blocker found.\nProceed with option A.",
        summary="Gemini found no blocker",
        root=tmp_path,
        output="answer-gemini.md",
    )

    answer = tmp_path / "session-1" / "answer-gemini.md"
    manifest = tmp_path / "session-1" / "_manifest.md"
    assert payload["schema"] == "agentx.ace_answer.v1"
    assert payload["ok"] is True
    assert payload["answer_exists"] is True
    assert answer.exists()
    assert "# ACE Answer: gemini" in answer.read_text(encoding="utf-8")
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "gemini answer: Gemini found no blocker" in manifest_text
    assert "answer-gemini.md" in manifest_text


def test_ace_answer_cli_outputs_jsonl_event(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-answer",
            "session-1",
            "--agent",
            "grok",
            "--answer",
            "Implementer answer",
            "--summary",
            "Grok can implement",
            "--root",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "ace_answer"
    assert envelope["data"]["schema"] == "agentx.ace_answer.v1"
    assert envelope["data"]["agent"] == "grok"
    assert envelope["data"]["ok"] is True


def test_ace_answer_blocks_empty_answer(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    payload = ace_answer_payload(
        session_id="session-1",
        agent="gemini",
        answer="  ",
        root=tmp_path,
    )

    assert payload["ok"] is False
    assert "answer_required" in payload["blockers"]


def test_ace_answer_blocks_existing_output(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )
    existing = tmp_path / "session-1" / "answer-gemini.md"
    existing.write_text("existing", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "ace-answer",
            "session-1",
            "--agent",
            "gemini",
            "--answer",
            "New answer",
            "--output",
            "answer-gemini.md",
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["blockers"] == ["answer_already_exists"]
    assert existing.read_text(encoding="utf-8") == "existing"
