import json

from typer.testing import CliRunner

from agentx.ace import ace_init_payload
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
