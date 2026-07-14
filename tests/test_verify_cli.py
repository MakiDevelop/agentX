import json
import subprocess

from typer.testing import CliRunner

from agentx.cli import app, default_verify_commands, verify_exit_code, verify_payload
from agentx.config import Settings


def test_default_verify_commands_detects_python_and_node(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")

    assert default_verify_commands(tmp_path) == [
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "pytest", "-q"],
        ["npm", "test"],
    ]


def test_verify_payload_runs_until_first_failure(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1 if "pytest" in command else 0,
            stdout="ruff ok" if "ruff" in command else "pytest failed",
            stderr="",
        )

    monkeypatch.setattr("agentx.cli.subprocess.run", fake_run)

    payload = verify_payload(Settings(workspace=tmp_path))

    assert payload["schema"] == "agentx.verify.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["ok"] is False
    assert payload["count"] == 2
    assert calls == [
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "pytest", "-q"],
    ]
    assert payload["recommended_command"] == "fix verification failures, then rerun agentx verify --json --fail-on-error"
    assert payload["recommended_kind"] == "fix_verify"
    assert payload["recommended_risk"] == "UNKNOWN"
    assert payload["checks"][0]["ok"] is True  # type: ignore[index]
    assert payload["checks"][1]["exit_code"] == 1  # type: ignore[index]


def test_verify_payload_reports_no_detected_commands(tmp_path) -> None:  # noqa: ANN001
    payload = verify_payload(Settings(workspace=tmp_path))

    assert payload["ok"] is False
    assert payload["count"] == 1
    assert payload["recommended_kind"] == "fix_verify"
    assert payload["recommended_risk"] == "UNKNOWN"
    assert payload["checks"][0]["command"] == ""  # type: ignore[index]
    assert "no default verification commands" in payload["checks"][0]["output"]  # type: ignore[index]


def test_verify_json_outputs_payload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agentx.cli.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["verify", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.verify.v1"
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["recommended_command"] == "agentx review --json"
    assert payload["recommended_kind"] == "review"
    assert payload["recommended_risk"] == "GREEN"
    assert payload["checks"][0]["command"] == "uv run ruff check ."


def test_verify_jsonl_outputs_event_envelope(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentx.cli.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="ok", stderr=""),
    )

    result = CliRunner().invoke(app, ["verify", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "verify"
    assert envelope["data"]["schema"] == "agentx.verify.v1"
    assert envelope["data"]["ok"] is True


def test_verify_fail_on_error_exits_one_but_prints_payload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentx.cli.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="failed", stderr=""),
    )

    result = CliRunner().invoke(
        app,
        ["verify", "--workspace", str(tmp_path), "--json", "--fail-on-error"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.verify.v1"
    assert payload["ok"] is False
    assert payload["checks"][0]["exit_code"] == 1


def test_verify_exit_code_is_opt_in(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentx.cli.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="failed", stderr=""),
    )
    payload = verify_payload(Settings(workspace=tmp_path))

    assert verify_exit_code(payload, fail_on_error=False) == 0
    assert verify_exit_code(payload, fail_on_error=True) == 1
