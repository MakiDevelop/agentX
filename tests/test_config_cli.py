import json
import shutil

import pytest
from typer.testing import CliRunner

from agentx.cli import app, config_payload
from agentx.config import Settings
from agentx.project_config import set_project_config


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


def test_memory_status_json_outputs_payload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTX_MEMORY_HALL_TOKEN", "secret-token")
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = CliRunner().invoke(app, ["memory-status", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.memory_status.v1"
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["memory_backend"] == "memhall"
    assert payload["legacy_memhall"]["token"] == "set"
    assert "secret-token" not in result.output


def test_memory_status_jsonl_outputs_event(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/amh" if name == "amh" else None)
    monkeypatch.setenv("AGENTX_MEMORY_BACKEND", "amh")

    result = CliRunner().invoke(app, ["memory-status", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "memory_status"
    assert envelope["data"]["schema"] == "agentx.memory_status.v1"
    assert envelope["data"]["amh"]["command"] == ["amh"]


def test_memory_status_exits_nonzero_when_amh_missing(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("AGENTX_MEMORY_BACKEND", "amh")

    result = CliRunner().invoke(app, ["memory-status", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["blockers"] == ["amh_cli_unavailable"]


def test_memory_read_json_outputs_payload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    fake_memory = type("FakeMemory", (), {"search": lambda self, query, namespace, limit: f"{namespace}:{limit}:{query}"})()
    monkeypatch.setattr("agentx.cli.build_cli_memory_client", lambda settings: fake_memory)

    result = CliRunner().invoke(app, ["memory-read", "handoff", "--workspace", str(tmp_path), "--limit", "2", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.memory_read.v1"
    assert payload["result"] == "project:agentX:2:handoff"


def test_memory_read_jsonl_outputs_event(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    fake_memory = type("FakeMemory", (), {"search": lambda self, query, namespace, limit: "ok"})()
    monkeypatch.setattr("agentx.cli.build_cli_memory_client", lambda settings: fake_memory)

    result = CliRunner().invoke(app, ["memory-read", "handoff", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "memory_read"
    assert envelope["data"]["schema"] == "agentx.memory_read.v1"


def test_memory_write_dry_run_does_not_call_backend(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    class FakeMemory:
        def __init__(self):
            self.called = False

        def write_aca(self, **kwargs):  # noqa: ANN003
            self.called = True
            return {"memory_id": "mem-1"}

    fake_memory = FakeMemory()
    monkeypatch.setattr("agentx.cli.build_cli_memory_client", lambda settings: fake_memory)

    result = CliRunner().invoke(app, ["memory-write", "preview only", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.memory_write.v1"
    assert payload["write"] is False
    assert payload["warnings"] == ["dry_run_no_memory_written"]
    assert fake_memory.called is False


def test_memory_write_with_write_calls_backend(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    calls = []

    class FakeMemory:
        def write_aca(self, **kwargs):  # noqa: ANN003
            calls.append(kwargs)
            return {"memory_id": "mem-1"}

    monkeypatch.setattr("agentx.cli.build_cli_memory_client", lambda settings: FakeMemory())

    result = CliRunner().invoke(
        app,
        [
            "memory-write",
            "write this",
            "--workspace",
            str(tmp_path),
            "--namespace",
            "project:test",
            "--tier",
            "human_confirmed",
            "--type",
            "fact",
            "--write",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["write"] is True
    assert payload["memory_result"] == {"memory_id": "mem-1"}
    assert calls == [
        {
            "content": "write this",
            "namespace": "project:test",
            "memory_type": "fact",
            "source_tier": "human_confirmed",
        }
    ]


def test_memory_write_jsonl_outputs_event(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    fake_memory = type("FakeMemory", (), {"write_aca": lambda self, **kwargs: {"memory_id": "mem-1"}})()
    monkeypatch.setattr("agentx.cli.build_cli_memory_client", lambda settings: fake_memory)

    result = CliRunner().invoke(app, ["memory-write", "preview", "--workspace", str(tmp_path), "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "memory_write"
    assert envelope["data"]["schema"] == "agentx.memory_write.v1"
    assert envelope["data"]["write"] is False


def test_memory_amh_local_store_cli_smoke_writes_reads_and_reports_status(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    if shutil.which("amh") is None:
        pytest.skip("AMH CLI is not installed")

    monkeypatch.delenv("AGENTX_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("AGENTX_AMH_STORE", raising=False)
    monkeypatch.delenv("AGENTX_AMH_PATH", raising=False)

    runner = CliRunner()
    store_path = tmp_path / ".agentx" / "amh" / "memory.json"
    namespace = "project:agentx-memory-smoke"
    content = "isolated AMH local store smoke marker 2026-07-15"

    for key, value in [
        ("memory_backend", "amh"),
        ("memory_amh_store", "json"),
        ("memory_amh_path", str(store_path)),
        ("namespace", namespace),
    ]:
        set_project_config(tmp_path, key, value)

    write_result = runner.invoke(
        app,
        [
            "memory-write",
            content,
            "--workspace",
            str(tmp_path),
            "--type",
            "fact",
            "--tier",
            "human_confirmed",
            "--write",
            "--json",
        ],
    )
    assert write_result.exit_code == 0, write_result.output
    write_payload = json.loads(write_result.output)
    assert write_payload["schema"] == "agentx.memory_write.v1"
    assert write_payload["ok"] is True
    assert write_payload["write"] is True
    assert write_payload["namespace"] == namespace
    assert write_payload["memory_type"] == "fact"
    assert write_payload["tier"] == "human_confirmed"
    assert write_payload["memory_result"]["status"] == "ok"
    assert store_path.exists()

    read_result = runner.invoke(
        app,
        [
            "memory-read",
            "local store smoke marker",
            "--workspace",
            str(tmp_path),
            "--limit",
            "5",
            "--json",
        ],
    )
    assert read_result.exit_code == 0, read_result.output
    read_payload = json.loads(read_result.output)
    assert read_payload["schema"] == "agentx.memory_read.v1"
    assert read_payload["ok"] is True
    assert read_payload["namespace"] == namespace
    assert content in read_payload["result"]

    status_result = runner.invoke(app, ["memory-status", "--workspace", str(tmp_path), "--json"])
    assert status_result.exit_code == 0, status_result.output
    status_payload = json.loads(status_result.output)
    assert status_payload["schema"] == "agentx.memory_status.v1"
    assert status_payload["ok"] is True
    assert status_payload["memory_backend"] == "amh"
    assert status_payload["namespace"] == namespace
    assert status_payload["amh"]["store"] == "json"
    assert status_payload["amh"]["path"] == str(store_path)
    assert status_payload["amh"]["path_exists"] is True
    assert status_payload["recommended_command"] == "agentx inspect --json"

    store_text = store_path.read_text(encoding="utf-8")
    assert content in store_text
