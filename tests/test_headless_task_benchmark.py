import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from typer.testing import CliRunner

from agentx.cli import app
from agentx.provider_registry import register_llm_backend


class BenchmarkFakeClient:
    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("benchmark fake backend exhausted")
        response = self.responses.pop(0)
        if on_delta is not None:
            on_delta(response)
        return response

    def list_models(self) -> list[str]:
        return ["benchmark-fake"]

    def close(self) -> None:
        return None

    def __enter__(self) -> "BenchmarkFakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _git(path: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _init_fixture_repo(path: Path) -> None:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "test@example.com"])
    _git(path, ["config", "user.name", "Test User"])
    (path / ".gitignore").write_text(".agentx/\n", encoding="utf-8")
    (path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(path, ["add", ".gitignore", "README.md"])
    _git(path, ["commit", "-m", "init"])


def test_headless_agent_benchmark_completes_task_artifacts_next_and_gate(tmp_path: Path) -> None:
    _init_fixture_repo(tmp_path)
    runner = CliRunner()
    responses = [
        json.dumps(
            {
                "type": "tool_call",
                "tool": "write_file",
                "args": {
                    "path": "BENCHMARK.md",
                    "content": "# Headless Benchmark\n\ncompleted by deterministic fake backend\n",
                },
            }
        ),
        json.dumps(
            {
                "type": "final",
                "content": "Created BENCHMARK.md and completed the deterministic headless benchmark.",
            }
        ),
    ]
    register_llm_backend(
        "benchmark_fake",
        lambda _base_url, _model, _timeout: BenchmarkFakeClient(responses),
        source_id="test_headless_task_benchmark",
    )

    result = runner.invoke(
        app,
        [
            "-p",
            "Create BENCHMARK.md with the benchmark completion marker.",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--backend",
            "benchmark_fake",
            "--model",
            "benchmark-fake",
            "--approval",
            "auto-approve",
            "--artifact-dir",
            ".agentx/runs/benchmark",
            "--no-memory",
            "--quiet",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "agentx.headless_result.v1"
    assert payload["exit_code"] == 0
    assert payload["termination"] == "final_success"
    assert payload["output"] == "Created BENCHMARK.md and completed the deterministic headless benchmark."
    assert payload["stats"]["tool_call_count"] == 1
    assert payload["session_path"].endswith(".agentx/runs/benchmark/session.session.jsonl")

    benchmark_file = tmp_path / "BENCHMARK.md"
    assert benchmark_file.read_text(encoding="utf-8") == "# Headless Benchmark\n\ncompleted by deterministic fake backend\n"

    artifact_dir = tmp_path / ".agentx" / "runs" / "benchmark"
    assert (artifact_dir / "session.session.jsonl").is_file()
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "handoff.md").is_file()
    artifact_payload = json.loads((artifact_dir / "result.json").read_text(encoding="utf-8"))
    assert artifact_payload["termination"] == "final_success"
    assert artifact_payload["exit_code"] == 0

    artifacts_result = runner.invoke(app, ["artifacts", "--workspace", str(tmp_path), "--json"])
    assert artifacts_result.exit_code == 0, artifacts_result.output
    artifacts_payload = json.loads(artifacts_result.output)
    assert artifacts_payload["latest_artifact"]["artifact_type"] == "headless_bundle"
    assert artifacts_payload["latest_artifact"]["relative_path"] == ".agentx/runs/benchmark"
    assert artifacts_payload["latest_artifact"]["exit_code"] == 0
    assert artifacts_payload["latest_artifact"]["has_session"] is True
    assert artifacts_payload["latest_artifact"]["has_handoff"] is True

    next_result = runner.invoke(app, ["next", "--workspace", str(tmp_path), "--json"])
    assert next_result.exit_code == 0, next_result.output
    next_payload = json.loads(next_result.output)
    assert next_payload["signals"]["dirty"] is True
    assert next_payload["signals"]["latest_artifact_type"] == "headless_bundle"
    assert next_payload["recommended_kind"] == "gate"
    assert next_payload["recommended_command"] == "agentx gate --json --fail-on-blocker"

    gate_result = runner.invoke(app, ["gate", "--workspace", str(tmp_path), "--skip-verify", "--json"])
    assert gate_result.exit_code == 0, gate_result.output
    gate_payload = json.loads(gate_result.output)
    assert gate_payload["schema"] == "agentx.gate.v1"
    assert gate_payload["review"]["diff"]["dirty"] is True
    assert gate_payload["doctor"]["workflow_artifact_health"]["status"] == "no_workflow_artifact"
