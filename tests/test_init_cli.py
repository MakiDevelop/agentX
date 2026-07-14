import json

from typer.testing import CliRunner

from agentx.cli import app, init_payload
from agentx.config import Settings


def _python_uv_workspace(path) -> None:  # noqa: ANN001
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (path / "uv.lock").write_text("", encoding="utf-8")


def test_init_payload_wraps_project_profile(tmp_path) -> None:  # noqa: ANN001
    _python_uv_workspace(tmp_path)
    settings = Settings(workspace=tmp_path)

    payload = init_payload(settings, namespace="project:demo")

    assert payload["schema"] == "agentx.init.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["namespace"] == "project:demo"
    assert payload["write_memory"] is False
    assert payload["memory_result"] is None
    assert payload["profile"]["schema"] == "agentx.project_profile.v1"
    assert payload["profile"]["detected"] == ["Python project", "uv-managed dependencies"]
    assert "uv run pytest -q" in payload["profile"]["test_commands"]


def test_init_json_outputs_read_only_profile(tmp_path) -> None:  # noqa: ANN001
    _python_uv_workspace(tmp_path)

    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path), "--namespace", "project:demo", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.init.v1"
    assert payload["namespace"] == "project:demo"
    assert payload["write_memory"] is False
    assert payload["memory_result"] is None
    assert payload["profile"]["workspace"] == str(tmp_path.resolve())


def test_init_jsonl_outputs_event_envelope(tmp_path) -> None:  # noqa: ANN001
    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "init"
    assert envelope["data"]["schema"] == "agentx.init.v1"
    assert envelope["data"]["profile"]["schema"] == "agentx.project_profile.v1"


def test_init_plain_outputs_table(tmp_path) -> None:  # noqa: ANN001
    _python_uv_workspace(tmp_path)

    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "agentX init" in result.output
    assert "Python project" in result.output
    assert "uv run pytest -q" in result.output
