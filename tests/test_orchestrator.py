from pathlib import Path
from types import SimpleNamespace

from helpers import make_settings

from agentx import cli
from agentx.orchestrator import Orchestrator
from agentx.tools import ToolRegistry, builtin_tools


class FakeOllama:
    model = "gemma4:31b"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def chat(self, messages, *, json_mode=False, on_delta=None, cancel_event=None):  # noqa: ANN001
        return self.responses.pop(0)


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"

    def write_structured(self, **kwargs):  # noqa: ANN003
        return {"entry_id": "mem-1"}


def _orch(tmp_path: Path, responses: list[str], **kwargs) -> Orchestrator:  # noqa: ANN003
    memory = FakeMemory()
    return Orchestrator(
        settings=make_settings(tmp_path, model="gemma4:31b", max_steps=4, learning_enabled=False),
        llm=FakeOllama(responses),
        memory=memory,  # type: ignore[arg-type]
        tools=ToolRegistry(builtin_tools(tmp_path, memory), auto_approve_yellow=True),  # type: ignore[arg-type]
        **kwargs,
    )


def test_worker_max_steps_default_is_long_enough_for_a_subtask(tmp_path: Path) -> None:
    orch = _orch(tmp_path, [])
    assert orch.worker_max_steps >= 16


def test_topo_sort_orders_dependencies(tmp_path: Path) -> None:
    orch = _orch(tmp_path, [])
    ordered = orch._topo_sort(
        [
            {"id": "s2", "description": "edit", "depends_on": ["s1"]},
            {"id": "s1", "description": "read", "depends_on": []},
        ]
    )
    assert [item["id"] for item in ordered] == ["s1", "s2"]


def test_topo_sort_keeps_original_order_on_cycle(tmp_path: Path) -> None:
    orch = _orch(tmp_path, [])
    tasks = [
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ]
    assert orch._topo_sort(tasks) == tasks


def test_build_check_passes_when_no_project_system(tmp_path: Path) -> None:
    orch = _orch(tmp_path, [])
    ok, output = orch._run_build_check()
    assert ok is True
    assert "no build system" in output


def test_fallback_single_agent_when_plan_is_not_json(tmp_path: Path) -> None:
    orch = _orch(
        tmp_path,
        [
            '{"type":"final","content":"cannot plan"}',
            '{"type":"final","content":"fallback done"}',
        ],
    )
    result = orch.run("幫我看一下這個 workspace")
    assert result.success
    assert result.subtask_results[0].subtask_id == "fallback"
    assert "fallback done" in result.summary


def test_run_print_prompt_auto_routes_complex_task_to_orchestrator(monkeypatch) -> None:  # noqa: ANN001
    seen: list[str] = []

    class FakeOrch:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            pass

        def run(self, prompt: str, namespace: str = "project:agentX") -> object:
            seen.append(prompt)
            return SimpleNamespace(summary="auto-orch")

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("single-agent loop should not run")

    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)
    monkeypatch.setattr("agentx.orchestrator.Orchestrator", FakeOrch)

    result = cli.run_print_prompt(
        "拆成子任務：先讀 loop，再拆 compact，最後補測試",
        namespace="project:test",
        agent_mode=True,
        return_metadata=True,
        suppress_trace=True,
    )
    assert isinstance(result, cli.HeadlessRunResult)
    assert result.output == "auto-orch"
    assert seen


def test_run_print_prompt_keeps_simple_task_on_single_agent(monkeypatch) -> None:  # noqa: ANN001
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

        def run(self, prompt: str, **kwargs) -> str:  # noqa: ANN003
            return "single-agent"

    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: (object(), object(), object()))
    monkeypatch.setattr(cli, "AgentLoop", FakeAgentLoop)

    result = cli.run_print_prompt(
        "demo",
        namespace="project:test",
        agent_mode=True,
        return_metadata=True,
        suppress_trace=True,
    )
    assert isinstance(result, cli.HeadlessRunResult)
    assert result.output == "single-agent"
