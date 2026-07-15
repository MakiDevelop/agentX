import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.ace import ace_answer_payload, ace_append_payload, ace_briefing_payload, ace_init_payload, ace_status_payload
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


def test_ace_status_payload_summarizes_session(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )
    ace_append_payload(
        session_id="session-1",
        section="question",
        text="Should Gemini review the diff?",
        root=tmp_path,
        agent="codex",
    )
    ace_briefing_payload(
        session_id="session-1",
        agent="gemini",
        role="Reviewer",
        task="Review current manifest",
        root=tmp_path,
        write=True,
    )
    ace_answer_payload(
        session_id="session-1",
        agent="gemini",
        answer="No blocker found.",
        summary="Gemini found no blocker",
        root=tmp_path,
        output="answer-gemini.md",
    )

    payload = ace_status_payload(session_id="session-1", root=tmp_path)

    assert payload["schema"] == "agentx.ace_status.v1"
    assert payload["ok"] is True
    assert payload["manifest_exists"] is True
    assert payload["counts"]["briefings"] == 1
    assert payload["counts"]["answers"] == 1
    assert payload["counts"]["open_questions"] == 1
    assert payload["briefings"][0]["name"] == "briefing-gemini.md"
    assert payload["answers"][0]["name"] == "answer-gemini.md"
    assert "Should Gemini review the diff?" in payload["open_questions"][0]
    assert payload["recommended_kind"] == "ace_briefing"


def test_ace_status_cli_outputs_jsonl_event(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    result = CliRunner().invoke(
        app,
        [
            "ace-status",
            "session-1",
            "--root",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "ace_status"
    assert envelope["data"]["schema"] == "agentx.ace_status.v1"
    assert envelope["data"]["counts"]["briefings"] == 0


def test_ace_write_cli_smoke_uses_temp_root_for_full_session_chain(tmp_path) -> None:  # noqa: ANN001
    runner = CliRunner()
    session_id = "session-write-smoke"

    init_result = runner.invoke(
        app,
        [
            "ace-init",
            session_id,
            "--goal",
            "Verify isolated ACE write path",
            "--route",
            "Codex: architect; Gemini: reviewer",
            "--root",
            str(tmp_path),
            "--write",
            "--json",
        ],
    )
    assert init_result.exit_code == 0, init_result.output
    init_payload = json.loads(init_result.output)
    assert init_payload["ok"] is True
    assert init_payload["write"] is True
    assert init_payload["root"] == str(tmp_path.resolve())
    assert init_payload["manifest_exists"] is True

    briefing_result = runner.invoke(
        app,
        [
            "ace-briefing",
            session_id,
            "--agent",
            "gemini",
            "--role",
            "Reviewer",
            "--task",
            "Review isolated ACE write path",
            "--root",
            str(tmp_path),
            "--write",
            "--json",
        ],
    )
    assert briefing_result.exit_code == 0, briefing_result.output
    briefing_payload = json.loads(briefing_result.output)
    assert briefing_payload["ok"] is True
    assert briefing_payload["write"] is True
    assert briefing_payload["briefing_exists"] is True
    assert briefing_payload["recommended_command"] == "agentx next --json"

    answer_result = runner.invoke(
        app,
        [
            "ace-answer",
            session_id,
            "--agent",
            "gemini",
            "--answer",
            "No blocker found in isolated ACE write smoke.",
            "--summary",
            "Gemini found no blocker",
            "--root",
            str(tmp_path),
            "--output",
            "answer-gemini.md",
            "--json",
        ],
    )
    assert answer_result.exit_code == 0, answer_result.output
    answer_payload = json.loads(answer_result.output)
    assert answer_payload["ok"] is True
    assert answer_payload["answer_exists"] is True
    assert answer_payload["recommended_command"] == "agentx next --json"

    status_result = runner.invoke(
        app,
        [
            "ace-status",
            session_id,
            "--root",
            str(tmp_path),
            "--json",
        ],
    )
    assert status_result.exit_code == 0, status_result.output
    status_payload = json.loads(status_result.output)
    assert status_payload["ok"] is True
    assert status_payload["root"] == str(tmp_path.resolve())
    assert status_payload["manifest_exists"] is True
    assert status_payload["counts"]["briefings"] == 1
    assert status_payload["counts"]["answers"] == 1
    assert status_payload["counts"]["open_questions"] == 0
    assert status_payload["briefings"][0]["name"] == "briefing-gemini.md"
    assert status_payload["answers"][0]["name"] == "answer-gemini.md"
    assert status_payload["recommended_command"] == "agentx next --json"

    session_dir = tmp_path / session_id
    assert (session_dir / "_manifest.md").exists()
    assert (session_dir / "briefing-gemini.md").exists()
    assert (session_dir / "answer-gemini.md").exists()
    manifest_text = (session_dir / "_manifest.md").read_text(encoding="utf-8")
    assert "Verify isolated ACE write path" in manifest_text
    assert "gemini answer: Gemini found no blocker" in manifest_text

    touched_paths = [
        init_payload["manifest_path"],
        briefing_payload["briefing_path"],
        answer_payload["answer_path"],
        status_payload["manifest_path"],
    ]
    for raw_path in touched_paths:
        path = Path(raw_path)
        assert path.is_relative_to(tmp_path.resolve())


def test_ace_status_blocks_missing_manifest(tmp_path) -> None:  # noqa: ANN001
    payload = ace_status_payload(session_id="session-1", root=tmp_path)

    assert payload["ok"] is False
    assert payload["blockers"] == ["manifest_not_found"]


def test_ace_status_caps_manifest(tmp_path) -> None:  # noqa: ANN001
    ace_init_payload(
        session_id="session-1",
        goal="Coordinate agents",
        root=tmp_path,
        write=True,
    )

    payload = ace_status_payload(session_id="session-1", root=tmp_path, max_manifest_chars=20)

    assert payload["ok"] is True
    assert payload["manifest_truncated"] is True
    assert len(payload["manifest"]) == 20
