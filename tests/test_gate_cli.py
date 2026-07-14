import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app, gate_exit_code, gate_payload
from agentx.config import Settings


def _git(path: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_repo_with_change(path: Path) -> None:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "test@example.com"])
    _git(path, ["config", "user.name", "Test User"])
    target = path / "note.txt"
    target.write_text("one\n", encoding="utf-8")
    _git(path, ["add", "note.txt"])
    _git(path, ["commit", "-m", "init"])
    target.write_text("one\ntwo\n", encoding="utf-8")


def _review(workspace: Path, *, ok: bool = True, commit_ready: bool = True, blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "schema": "agentx.review.v1",
        "workspace": str(workspace.resolve()),
        "generated_at": "2026-01-02T00:00:00",
        "ok": ok,
        "commit_ready": commit_ready,
        "blockers": blockers or [],
        "warnings": [],
        "diff": {"schema": "agentx.diff.v1", "dirty": True},
        "verify": {"schema": "agentx.verify.v1", "ok": True},
        "next_commands": ["agentx diff --json"],
    }


def _doctor(workspace: Path, *, ok: bool = True) -> dict[str, object]:
    return {
        "schema": "agentx.doctor.v1",
        "workspace": str(workspace.resolve()),
        "generated_at": "2026-01-02T00:00:00",
        "live_probes": False,
        "ok": ok,
        "checks": [{"name": "git", "ok": ok, "detail": "ok" if ok else "failed"}],
    }


def _approvals(workspace: Path, *, ok: bool = True, denied_count: int = 0) -> dict[str, object]:
    return {
        "schema": "agentx.approvals.v1",
        "workspace": str(workspace.resolve()),
        "session": "latest",
        "path": str(workspace / ".agentx" / "sessions" / "latest.jsonl") if ok else None,
        "ok": ok,
        "denied_only": False,
        "count": denied_count,
        "denied_count": denied_count,
        "receipts": [{"tool": "apply_patch", "allowed": False}] if denied_count else [],
        "detail": "" if ok else "transcript not found: latest",
    }


def test_gate_payload_passes_when_review_doctor_and_approvals_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _review(settings.workspace))
    monkeypatch.setattr("agentx.cli.doctor_payload", lambda settings, live_probes=False: _doctor(settings.workspace))
    monkeypatch.setattr("agentx.cli.approvals_payload", lambda settings, session="latest", limit=20: _approvals(settings.workspace))

    payload = gate_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.gate.v1"
    assert payload["ok"] is True
    assert payload["commit_ready"] is True
    assert payload["blockers"] == []
    assert payload["review"]["schema"] == "agentx.review.v1"  # type: ignore[index]
    assert payload["doctor"]["schema"] == "agentx.doctor.v1"  # type: ignore[index]
    assert payload["approvals"]["schema"] == "agentx.approvals.v1"  # type: ignore[index]
    assert "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker" in payload["next_commands"]


def test_gate_payload_carries_review_blockers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "agentx.cli.review_payload",
        lambda settings, timeout=120, run_verify=True: _review(settings.workspace, ok=False, commit_ready=False, blockers=["verify_failed"]),
    )
    monkeypatch.setattr("agentx.cli.doctor_payload", lambda settings, live_probes=False: _doctor(settings.workspace))
    monkeypatch.setattr("agentx.cli.approvals_payload", lambda settings, session="latest", limit=20: _approvals(settings.workspace))

    payload = gate_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["commit_ready"] is False
    assert payload["blockers"] == ["verify_failed"]
    assert gate_exit_code(payload, fail_on_blocker=True) == 1


def test_gate_payload_blocks_when_doctor_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _review(settings.workspace))
    monkeypatch.setattr("agentx.cli.doctor_payload", lambda settings, live_probes=False: _doctor(settings.workspace, ok=False))
    monkeypatch.setattr("agentx.cli.approvals_payload", lambda settings, session="latest", limit=20: _approvals(settings.workspace))

    payload = gate_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["commit_ready"] is False
    assert payload["blockers"] == ["doctor_failed"]


def test_gate_payload_blocks_when_approval_was_denied(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _review(settings.workspace))
    monkeypatch.setattr("agentx.cli.doctor_payload", lambda settings, live_probes=False: _doctor(settings.workspace))
    monkeypatch.setattr(
        "agentx.cli.approvals_payload",
        lambda settings, session="latest", limit=20: _approvals(settings.workspace, denied_count=1),
    )

    payload = gate_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["commit_ready"] is False
    assert payload["blockers"] == ["approval_denied"]


def test_gate_payload_warns_when_approval_session_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentx.cli.review_payload", lambda settings, timeout=120, run_verify=True: _review(settings.workspace))
    monkeypatch.setattr("agentx.cli.doctor_payload", lambda settings, live_probes=False: _doctor(settings.workspace))
    monkeypatch.setattr("agentx.cli.approvals_payload", lambda settings, session="latest", limit=20: _approvals(settings.workspace, ok=False))

    payload = gate_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is True
    assert payload["commit_ready"] is True
    assert payload["warnings"] == ["approvals_unavailable"]


def test_gate_payload_skip_options_warn_and_omit_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "agentx.cli.review_payload",
        lambda settings, timeout=120, run_verify=False: _review(settings.workspace, commit_ready=False),
    )

    payload = gate_payload(
        Settings(workspace=tmp_path),
        run_verify=False,
        run_doctor=False,
        run_approvals=False,
    )

    assert payload["ok"] is True
    assert payload["commit_ready"] is False
    assert payload["doctor"] is None
    assert payload["approvals"] is None
    assert payload["warnings"] == ["doctor_skipped", "approvals_skipped"]


def test_gate_json_outputs_payload(tmp_path: Path, monkeypatch) -> None:
    _git_repo_with_change(tmp_path)
    monkeypatch.setattr("agentx.cli.verify_payload", lambda settings, timeout=120: {"schema": "agentx.verify.v1", "ok": True})

    result = CliRunner().invoke(
        app,
        ["gate", "--workspace", str(tmp_path), "--skip-doctor", "--skip-approvals", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.gate.v1"
    assert payload["review"]["schema"] == "agentx.review.v1"
    assert payload["doctor"] is None
    assert payload["approvals"] is None


def test_gate_jsonl_outputs_event_envelope(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["gate", "--workspace", str(tmp_path), "--skip-verify", "--skip-doctor", "--skip-approvals", "--output-format", "jsonl"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "gate"
    assert envelope["data"]["schema"] == "agentx.gate.v1"


def test_gate_fail_on_blocker_exits_one_but_prints_payload(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["gate", "--workspace", str(tmp_path), "--skip-doctor", "--skip-approvals", "--json", "--fail-on-blocker"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.gate.v1"
    assert "verify_failed" in payload["blockers"]


def test_gate_plain_outputs_summary(tmp_path: Path) -> None:
    _git_repo_with_change(tmp_path)

    result = CliRunner().invoke(
        app,
        ["gate", "--workspace", str(tmp_path), "--skip-verify", "--skip-doctor", "--skip-approvals"],
    )

    assert result.exit_code == 0, result.output
    assert "agentX gate" in result.output
    assert "commit_ready" in result.output
    assert "doctor_skipped" in result.output
