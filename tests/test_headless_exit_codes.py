import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agentx import cli
from agentx.session_store import SessionStore


def test_headless_exit_code_success() -> None:
    assert cli.headless_exit_code("完成") == 0


def test_headless_exit_code_task_failure() -> None:
    assert cli.headless_exit_code("任務失敗：工具 read_file 仍有未解決的錯誤") == 1
    assert cli.headless_exit_code("工具執行失敗：not found") == 1


def test_headless_exit_code_agent_control_failure() -> None:
    assert cli.headless_exit_code("模型沒有輸出有效的工具呼叫 JSON，已停止。") == 2
    assert cli.headless_exit_code("") == 2


def test_headless_exit_code_cancelled() -> None:
    assert cli.headless_exit_code("Ollama request cancelled") == 130


def test_structured_headless_exit_code_overrides_success_text() -> None:
    assert cli.headless_exit_code("看起來完成", termination="final_failed", failing_tools=("run_tests",)) == 1
    assert cli.headless_exit_code("完成", termination="max_steps_exceeded") == 2
    assert cli.headless_exit_code("完成", termination="cancelled") == 130


def test_structured_headless_exit_code_clean_final_success() -> None:
    assert cli.headless_exit_code("任務失敗這幾個字只是被引用", termination="final_success") == 0
    assert cli.headless_exit_code("done", termination="direct_tool_success") == 0
    assert cli.headless_exit_code("done", termination="direct_tool_failure") == 1


def test_print_prompt_uses_headless_exit_code(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "任務失敗：工具失敗")

    result = runner.invoke(cli.app, ["-p", "demo", "--agent"])

    assert result.exit_code == 1
    assert "任務失敗" in result.output


def test_print_prompt_success_exit_zero(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "完成")

    result = runner.invoke(cli.app, ["-p", "demo"])

    assert result.exit_code == 0
    assert "完成" in result.output


def test_print_prompt_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(
            output="文字看似完成",
            termination="final_failed",
            failing_tools=("run_tests",),
        ),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent"])

    assert result.exit_code == 1
    assert "文字看似完成" in result.output


def test_headless_json_payload_includes_stats() -> None:
    payload = cli.headless_json_payload(
        cli.HeadlessRunResult(
            output="完成",
            termination="final_success",
            stats={"message_count": 3, "error_count": 0},
        ),
        exit_code=0,
    )

    data = json.loads(payload)

    assert data["output"] == "完成"
    assert data["exit_code"] == 0
    assert data["termination"] == "final_success"
    assert data["failing_tools"] == []
    assert data["stats"]["message_count"] == 3
    assert data["session_path"] is None
    assert "phases" not in data


def test_headless_json_payload_includes_optional_phases() -> None:
    payload = cli.headless_json_payload(
        cli.HeadlessRunResult(
            output="combined",
            termination="final_success",
            phases=(
                {"name": "plan", "output": "PLAN"},
                {"name": "execution", "output": "EXEC"},
            ),
        ),
        exit_code=0,
    )

    data = json.loads(payload)

    assert data["output"] == "combined"
    assert data["phases"] == [
        {"name": "plan", "output": "PLAN"},
        {"name": "execution", "output": "EXEC"},
    ]


def test_wants_json_output_accepts_json_alias() -> None:
    assert cli.wants_json_output(False, "json") is True
    assert cli.wants_json_output(True, "plain") is True
    assert cli.wants_json_output(False, "plain") is False


def test_wants_json_output_rejects_unknown_format() -> None:
    try:
        cli.wants_json_output(False, "yaml")
    except Exception as exc:
        assert "plain, json" in str(exc)
    else:
        raise AssertionError("unknown output format should fail")


def test_load_headless_prompt_reads_workspace_file(tmp_path: Path) -> None:
    prompt = tmp_path / "briefing.md"
    prompt.write_text("DO THE THING", encoding="utf-8")

    assert cli.load_headless_prompt(None, "briefing.md", tmp_path) == "DO THE THING"


def test_load_headless_prompt_rejects_ambiguous_sources(tmp_path: Path) -> None:
    prompt = tmp_path / "briefing.md"
    prompt.write_text("DO THE THING", encoding="utf-8")

    try:
        cli.load_headless_prompt("inline", "briefing.md", tmp_path)
    except Exception as exc:
        assert "only one prompt source" in str(exc)
    else:
        raise AssertionError("ambiguous prompt sources should fail")


def test_load_headless_prompt_reads_stdin(tmp_path: Path) -> None:
    assert (
        cli.load_headless_prompt(
            None,
            None,
            tmp_path,
            stdin_prompt=True,
            stdin_reader=StringIO("PROMPT FROM STDIN"),
        )
        == "PROMPT FROM STDIN"
    )


def test_load_headless_prompt_blocks_workspace_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-briefing.md"
    outside.write_text("NOPE", encoding="utf-8")

    try:
        cli.load_headless_prompt(None, str(outside), tmp_path)
    except Exception as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("prompt file outside workspace should fail")


def test_resolve_session_store_path_latest_and_name(tmp_path: Path) -> None:
    sessions = tmp_path / ".agentx" / "sessions"
    sessions.mkdir(parents=True)
    first = SessionStore(sessions / "20260101-000000-a.session.jsonl")
    first.append("system", "session_start")
    second = SessionStore(sessions / "20260102-000000-b.session.jsonl")
    second.append("system", "session_start")

    assert cli.resolve_session_store_path(tmp_path, "latest") == second.path
    assert cli.resolve_session_store_path(tmp_path, second.path.name) == second.path
    assert cli.resolve_session_store_path(tmp_path, second.path.stem) == second.path
    assert first.path != second.path


def test_resolve_session_store_path_rejects_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.session.jsonl"
    outside.write_text("{}", encoding="utf-8")

    try:
        cli.resolve_session_store_path(tmp_path, str(outside))
    except FileNotFoundError as exc:
        assert "Saved headless session not found" in str(exc)
    else:
        raise AssertionError("outside session path should be rejected")


def test_headless_run_stats_summarizes_session_state() -> None:
    session = SimpleNamespace(
        message_count=9,
        context_tokens_estimate=1234,
        error_history=[object(), object()],
        compaction_count=1,
        model_turn_count=4,
        tool_call_count=2,
        reflection_count=1,
        pending_verifies={"src/a.py"},
        tasks=[
            {"status": "pending"},
            {"status": "in_progress"},
            {"status": "done"},
            {"status": "blocked"},
            {"status": "unknown"},
        ],
    )

    stats = cli.headless_run_stats(session)  # type: ignore[arg-type]

    assert stats["message_count"] == 9
    assert stats["context_tokens_estimate"] == 1234
    assert stats["error_count"] == 2
    assert stats["compaction_count"] == 1
    assert stats["model_turn_count"] == 4
    assert stats["tool_call_count"] == 2
    assert stats["reflection_count"] == 1
    assert stats["pending_verifies"] == ["src/a.py"]
    assert stats["task_counts"] == {
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "blocked": 1,
    }


def test_print_prompt_json_output_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(
        cli,
        "run_print_prompt",
        lambda *args, **kwargs: cli.HeadlessRunResult(
            output="文字看似完成",
            termination="final_failed",
            failing_tools=("run_tests",),
            stats={"message_count": 7, "error_count": 1},
        ),
    )

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 1
    assert data["output"] == "文字看似完成"
    assert data["exit_code"] == 1
    assert data["termination"] == "final_failed"
    assert data["failing_tools"] == ["run_tests"]
    assert data["stats"]["error_count"] == 1


def test_print_prompt_output_format_json_uses_structured_metadata(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["output"] == "ok"
    assert data["termination"] == "final_success"
    assert captured["suppress_trace"] is True


def test_print_prompt_uses_prompt_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    prompt = tmp_path / "briefing.md"
    prompt.write_text("PROMPT FROM FILE", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["--prompt-file", "briefing.md", "--agent", "--output-format", "json"],
        env={"AGENTX_WORKSPACE": str(tmp_path)},
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "PROMPT FROM FILE"
    assert captured["agent_mode"] is True
    assert data["output"] == "ok"


def test_print_prompt_uses_stdin(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["--stdin", "--agent", "--output-format", "json"],
        input="PROMPT FROM STDIN",
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "PROMPT FROM STDIN"
    assert captured["agent_mode"] is True
    assert data["output"] == "ok"


def test_print_prompt_rejects_unknown_output_format(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    monkeypatch.setattr(cli, "run_print_prompt", lambda *args, **kwargs: "should not run")

    result = runner.invoke(cli.app, ["-p", "demo", "--output-format", "yaml"])

    assert result.exit_code != 0
    assert "plain, json" in result.output


def test_print_prompt_forwards_session_flags(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path="/tmp/s.session.jsonl")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["-p", "demo", "--agent", "--save-session", "--resume-session", "latest", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["save_session"] is True
    assert captured["resume_session"] == "latest"
    assert captured["suppress_trace"] is True
    assert captured["max_steps"] is None
    assert captured["backend_override"] is None
    assert captured["model_override"] is None
    assert captured["timeout_override"] is None
    assert data["session_path"] == "/tmp/s.session.jsonl"


def test_print_prompt_forwards_backend_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--backend", "llama_cpp"])

    assert result.exit_code == 0
    assert captured["backend_override"] == "llama_cpp"


def test_print_prompt_forwards_model_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--model", "gpt-oss:20b"])

    assert result.exit_code == 0
    assert captured["model_override"] == "gpt-oss:20b"


def test_print_prompt_forwards_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--timeout", "180"])

    assert result.exit_code == 0
    assert captured["timeout_override"] == 180.0


def test_print_prompt_forwards_max_steps(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["-p", "demo", "--agent", "--max-steps", "2"])

    assert result.exit_code == 0
    assert captured["max_steps"] == 2
    assert "ok" in result.output


def test_run_print_prompt_plan_then_execute_runs_two_phases(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, bool | None]] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=5,
                context_tokens_estimate=100,
                error_history=[],
                compaction_count=0,
                model_turn_count=2,
                tool_call_count=1,
                reflection_count=1,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None) -> str:
            calls.append((prompt, plan_only))
            if plan_only:
                return "PLAN_RESULT"
            return "EXECUTION_RESULT"

    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo task",
        namespace="project:test",
        agent_mode=True,
        plan_then_execute=True,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert result.output == "## Plan\nPLAN_RESULT\n\n## Execution\nEXECUTION_RESULT"
    assert result.phases == (
        {"name": "plan", "output": "PLAN_RESULT"},
        {"name": "execution", "output": "EXECUTION_RESULT"},
    )
    assert result.termination == "final_success"
    assert calls[0][1] is True
    assert "純 PLAN MODE" in calls[0][0]
    assert calls[1][1] is False
    assert "EXECUTE MODE" in calls[1][0]
    assert "PLAN_RESULT" in calls[1][0]


def test_run_print_prompt_uses_model_override(monkeypatch) -> None:  # noqa: ANN001
    seen_models: list[str] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen_models.append(settings.model)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        model_override="gpt-oss:20b",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_models == ["gpt-oss:20b"]


def test_run_print_prompt_uses_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    seen_timeouts: list[float] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, **kwargs):  # noqa: ANN001
        seen_timeouts.append(settings.ollama_timeout)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        timeout_override=180.0,
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_timeouts == [180.0]


def test_run_print_prompt_forwards_backend_override_to_runtime(monkeypatch) -> None:  # noqa: ANN001
    seen_backends: list[str | None] = []

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.session = SimpleNamespace(
                message_count=1,
                context_tokens_estimate=10,
                error_history=[],
                compaction_count=0,
                model_turn_count=0,
                tool_call_count=0,
                reflection_count=0,
                pending_verifies=set(),
                tasks=[],
                last_termination="final_success",
                last_failing_tools=set(),
            )

        def run(self, prompt: str, *, namespace: str, plan_only: bool | None = None) -> str:
            return "ok"

    def fake_build_runtime(settings, *args, backend_override=None, **kwargs):  # noqa: ANN001
        seen_backends.append(backend_override)
        return object(), object(), object()

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        backend_override="llama_cpp",
        return_metadata=True,
        suppress_trace=True,
    )

    assert isinstance(result, cli.HeadlessRunResult)
    assert seen_backends == ["llama_cpp"]


def test_build_runtime_backend_override_wins_over_env(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    seen: dict[str, object] = {}

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "base_url": base_url, "model": model, "timeout": timeout})
        return object()

    monkeypatch.setenv("AGENTX_BACKEND", "ollama")
    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    cli.build_runtime(make_settings(tmp_path), backend_override="llama_cpp")

    assert seen["name"] == "llama_cpp"


def test_build_runtime_uses_timeout_from_settings(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from helpers import make_settings

    seen: dict[str, object] = {}

    def fake_get_llm_client(name: str, base_url: str, model: str, timeout: float):  # noqa: ANN001
        seen.update({"name": name, "timeout": timeout})
        return object()

    monkeypatch.setattr(cli, "register_builtin_backends", lambda: None)
    monkeypatch.setattr(cli, "get_llm_client", fake_get_llm_client)

    cli.build_runtime(make_settings(tmp_path).with_updates(ollama_timeout=222.0))

    assert seen["timeout"] == 222.0


def test_ask_uses_shared_headless_runner_and_forwards_session_flags(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success", session_path="/tmp/s.session.jsonl")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(
        cli.app,
        ["ask", "demo", "--save-session", "--resume-session", "latest", "--max-steps", "3", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert captured["args"][0] == "demo"
    assert captured["agent_mode"] is True
    assert captured["return_metadata"] is True
    assert captured["suppress_trace"] is True
    assert captured["save_session"] is True
    assert captured["resume_session"] == "latest"
    assert captured["max_steps"] == 3
    assert captured["plan_then_execute"] is False
    assert captured["backend_override"] is None
    assert captured["model_override"] is None
    assert captured["timeout_override"] is None
    assert data["session_path"] == "/tmp/s.session.jsonl"


def test_ask_forwards_plan_then_execute(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--plan-then-execute"])

    assert result.exit_code == 0
    assert captured["plan_then_execute"] is True


def test_ask_forwards_backend_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--backend", "llama_cpp"])

    assert result.exit_code == 0
    assert captured["backend_override"] == "llama_cpp"


def test_ask_forwards_model_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--model", "gpt-oss:20b"])

    assert result.exit_code == 0
    assert captured["model_override"] == "gpt-oss:20b"


def test_ask_forwards_timeout_override(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--timeout", "180"])

    assert result.exit_code == 0
    assert captured["timeout_override"] == 180.0


def test_ask_output_format_json(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_print_prompt(*args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return cli.HeadlessRunResult(output="ok", termination="final_success")

    monkeypatch.setattr(cli, "run_print_prompt", fake_run_print_prompt)

    result = runner.invoke(cli.app, ["ask", "demo", "--output-format", "json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["output"] == "ok"
    assert captured["suppress_trace"] is True
