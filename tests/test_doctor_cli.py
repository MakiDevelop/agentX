import json
import subprocess

from typer.testing import CliRunner

from agentx.cli import app, doctor_payload_from_checks
from agentx.config import Settings


def _git_init(path) -> None:  # noqa: ANN001
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_doctor_payload_from_checks_aggregates_ok(tmp_path) -> None:  # noqa: ANN001
    settings = Settings(workspace=tmp_path)

    payload = doctor_payload_from_checks(
        [
            ("uv", True, "uv 0.1"),
            ("git", False, "not a git repository"),
        ],
        settings=settings,
        live_probes=False,
    )

    assert payload["schema"] == "agentx.doctor.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["live_probes"] is False
    assert payload["ok"] is False
    assert payload["checks"] == [
        {"name": "uv", "ok": True, "detail": "uv 0.1"},
        {"name": "git", "ok": False, "detail": "not a git repository"},
    ]


def test_doctor_static_json_outputs_local_checks(tmp_path) -> None:  # noqa: ANN001
    _git_init(tmp_path)

    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.doctor.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["live_probes"] is False
    assert payload["ok"] is True
    names = {check["name"] for check in payload["checks"]}
    assert names == {"uv", "git", "task_migration (MT22)"}


def test_doctor_static_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "doctor"
    assert envelope["data"]["schema"] == "agentx.doctor.v1"
    assert envelope["data"]["live_probes"] is False


def test_doctor_static_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--static"])

    assert result.exit_code == 0, result.output
    assert "agentX doctor" in result.output
    assert "uv" in result.output
    assert "git" in result.output
