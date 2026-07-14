import json
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, approvals_exit_code, approvals_payload
from agentx.config import Settings


def _write_approval_session(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                '{"ts":"2026-01-02T00:00:00","event":"session_start","model":"gemma4:31b","namespace":"project:test"}',
                '{"ts":"2026-01-02T00:00:01","event":"approval","tool":"memory_write","risk":"YELLOW","approval_mode":"auto","source":"auto_approved","allowed":true}',
                '{"ts":"2026-01-02T00:00:02","event":"approval","tool":"apply_patch","risk":"YELLOW","approval_mode":"ask","source":"manual_denied","allowed":false}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_approvals_payload_lists_receipts(tmp_path) -> None:  # noqa: ANN001
    session = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    _write_approval_session(session)

    payload = approvals_payload(Settings(workspace=tmp_path), session="20260102-000000")

    assert payload["schema"] == "agentx.approvals.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["session"] == "20260102-000000"
    assert payload["ok"] is True
    assert payload["path"] == str(session)
    assert payload["count"] == 2
    assert payload["denied_count"] == 1
    assert payload["receipts"][1]["tool"] == "apply_patch"  # type: ignore[index]


def test_approvals_payload_handles_missing_session(tmp_path) -> None:  # noqa: ANN001
    payload = approvals_payload(Settings(workspace=tmp_path), session="missing")

    assert payload["ok"] is False
    assert payload["path"] is None
    assert payload["count"] == 0
    assert payload["receipts"] == []
    assert payload["detail"] == "transcript not found: missing"


def test_approvals_json_outputs_denied_filter(tmp_path) -> None:  # noqa: ANN001
    _write_approval_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(
        app,
        ["approvals", "20260102-000000", "--workspace", str(tmp_path), "--denied", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.approvals.v1"
    assert payload["denied_only"] is True
    assert payload["count"] == 1
    assert payload["denied_count"] == 1
    assert payload["receipts"][0]["tool"] == "apply_patch"
    assert payload["receipts"][0]["allowed"] is False


def test_approvals_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    _write_approval_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(
        app,
        ["approvals", "20260102-000000", "--workspace", str(tmp_path), "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "approvals"
    assert envelope["data"]["schema"] == "agentx.approvals.v1"
    assert envelope["data"]["count"] == 2


def test_approvals_plain_outputs_source_and_receipts(tmp_path) -> None:  # noqa: ANN001
    session = tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl"
    _write_approval_session(session)

    result = CliRunner().invoke(app, ["approvals", "20260102-000000", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "source:" in result.output
    assert session.name in result.output
    assert "Approval receipts: 2 most recent" in result.output
    assert "memory_write allowed source=auto_approved mode=auto" in result.output
    assert "apply_patch denied source=manual_denied mode=ask" in result.output


def test_approvals_fail_on_denied_exits_one_but_prints_payload(tmp_path) -> None:  # noqa: ANN001
    _write_approval_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")

    result = CliRunner().invoke(
        app,
        [
            "approvals",
            "20260102-000000",
            "--workspace",
            str(tmp_path),
            "--json",
            "--fail-on-denied",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.approvals.v1"
    assert payload["denied_count"] == 1


def test_approvals_exit_code_is_opt_in(tmp_path) -> None:  # noqa: ANN001
    _write_approval_session(tmp_path / ".agentx" / "sessions" / "20260102-000000.jsonl")
    payload = approvals_payload(Settings(workspace=tmp_path), session="20260102-000000")

    assert approvals_exit_code(payload, fail_on_denied=False) == 0
    assert approvals_exit_code(payload, fail_on_denied=True) == 1
