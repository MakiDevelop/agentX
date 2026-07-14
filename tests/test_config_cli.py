import json

from typer.testing import CliRunner

from agentx.cli import app, config_payload
from agentx.config import Settings


def test_config_payload_uses_safe_token_status(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTX_MEMORY_HALL_TOKEN", "secret-token")
    settings = Settings(workspace=tmp_path)

    payload = config_payload(settings, namespace="project:test", mode="agent", approval="ask")

    assert payload["schema"] == "agentx.config.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["namespace"] == "project:test"
    assert payload["mode"] == "agent"
    assert payload["approval"] == "ask"
    assert payload["memory_hall_token"] == "set"
    assert "secret-token" not in json.dumps(payload)


def test_config_json_outputs_resolved_config(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["config", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.config.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["namespace"] == "project:agentX"
    assert payload["mode"] == "chat"
    assert payload["memory_hall_token"] in {"set", "missing"}


def test_config_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["config", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "config"
    assert envelope["data"]["schema"] == "agentx.config.v1"


def test_config_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["config", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX config" in result.output
    assert "workspace" in result.output
    assert "memory_hall_token" in result.output


def test_config_cli_accepts_overrides(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(
        app,
        [
            "config",
            "--workspace",
            str(tmp_path),
            "--namespace",
            "project:demo",
            "--mode",
            "ask",
            "--approval",
            "auto-approve",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["namespace"] == "project:demo"
    assert payload["mode"] == "agent"
    assert payload["approval"] == "auto"
