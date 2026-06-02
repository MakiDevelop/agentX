import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from agentx.config import Settings
from agentx.coordinator import Coordinator, CoordinatorError
from agentx.protocol import Risk
from agentx.tools import ToolRegistry


class FakeOllama:
    model = "fake"

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, str]], bool]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        self.calls.append((list(messages), json_mode))
        return self.responses.pop(0)


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "ok"


class _ProbeTool:
    name = "probe"
    description = "no-op probe"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return "probe ok"


def _settings(workspace: Path, max_steps: int = 5) -> Settings:
    return Settings.from_values(
        model="fake",
        ollama_url="http://localhost:11434",
        ollama_timeout=60,
        memory_hall_url="http://localhost:9100",
        memory_hall_token=None,
        max_steps=max_steps,
        context_limit_tokens=32768,
        auto_handoff=False,
        persona="default",
        workspace=workspace,
    )


def _coordinator(tmp_path: Path, responses: Sequence[str], tools: list[Any] | None = None) -> tuple[Coordinator, FakeOllama]:
    ollama = FakeOllama(responses)
    memory = FakeMemory()
    registry = ToolRegistry(tools or [])
    settings = _settings(tmp_path)
    coordinator = Coordinator(
        settings=settings,
        ollama=ollama,
        tools=registry,
        memory=memory,  # type: ignore[arg-type]
    )
    return coordinator, ollama


def test_coordinator_executes_plan_in_order(tmp_path: Path) -> None:
    coordinator, ollama = _coordinator(
        tmp_path,
        [
            '{"steps": [{"title": "Step A", "details": "do A"}, {"title": "Step B", "details": "do B"}]}',
            '{"type":"final","content":"A done"}',
            '{"type":"final","content":"B done"}',
            "All steps completed.",
        ],
    )
    result = coordinator.run("test goal")

    assert [s.title for s in result.plan.steps] == ["Step A", "Step B"]
    assert [r.summary for r in result.step_results] == ["A done", "B done"]
    assert all(r.success for r in result.step_results)
    assert result.success
    assert "completed" in result.final.lower()
    assert len(ollama.calls) == 4


def test_coordinator_step_sees_prior_summaries(tmp_path: Path) -> None:
    coordinator, ollama = _coordinator(
        tmp_path,
        [
            '{"steps": [{"title": "first", "details": "f"}, {"title": "second", "details": "s"}]}',
            '{"type":"final","content":"first summary"}',
            '{"type":"final","content":"second summary"}',
            "ok",
        ],
    )
    coordinator.run("g")

    second_step_messages = ollama.calls[2][0]
    user_msg = next(m for m in second_step_messages if m["role"] == "user")
    assert "first summary" in user_msg["content"]
    assert "first" in user_msg["content"]


def test_coordinator_marks_failure_when_step_stops(tmp_path: Path) -> None:
    coordinator, _ = _coordinator(
        tmp_path,
        [
            '{"steps": [{"title": "only", "details": "x"}]}',
            "not valid json at all",
            "not valid json at all",
            "still bogus",
            "and again",
            "and again",
            "and again",
            "and again",
            "merge note",
        ],
    )
    result = coordinator.run("force failure")

    assert len(result.step_results) == 1
    assert not result.step_results[0].success
    assert not result.success


def test_coordinator_continues_after_failure(tmp_path: Path) -> None:
    plan_json = (
        '{"steps": ['
        '{"title": "fail", "details": "f"},'
        '{"title": "ok", "details": "o"}'
        "]}"
    )
    coordinator, _ = _coordinator(
        tmp_path,
        [
            plan_json,
            "bogus",
            "bogus",
            "bogus",
            "bogus",
            "bogus",
            '{"type":"final","content":"second step succeeded"}',
            "report",
        ],
    )
    result = coordinator.run("mixed")

    assert len(result.step_results) == 2
    assert not result.step_results[0].success
    assert result.step_results[1].success
    assert not result.success


def test_coordinator_raises_on_unparseable_plan(tmp_path: Path) -> None:
    coordinator, _ = _coordinator(tmp_path, ["not json at all"])
    with pytest.raises(CoordinatorError):
        coordinator.run("g")


def test_coordinator_handles_empty_plan(tmp_path: Path) -> None:
    coordinator, _ = _coordinator(tmp_path, ['{"steps": []}'])
    result = coordinator.run("g")
    assert result.plan.steps == []
    assert result.step_results == []
    assert not result.success
    assert "empty" in result.final.lower() or "plan" in result.final.lower()


class _FailingTool:
    name = "fake_run"
    description = "always returns exit=1"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        return "$ thing\nexit=1\nerror"


def test_coordinator_rejects_plan_exceeding_max_steps(tmp_path: Path) -> None:
    # Plan with 8 steps exceeds PLAN_MAX_STEPS (7) → Pydantic validation
    # fails inside Coordinator._plan, wrapped in CoordinatorError (review N6).
    big_plan_steps = ",".join(
        f'{{"title": "s{i}", "details": "d"}}' for i in range(8)
    )
    plan_json = f'{{"steps": [{big_plan_steps}]}}'

    coordinator, _ = _coordinator(tmp_path, [plan_json])
    with pytest.raises(CoordinatorError, match="plan JSON invalid"):
        coordinator.run("goal")


def test_coordinator_step_fails_when_session_has_unresolved_failing_tool(tmp_path: Path) -> None:
    """Sub-agent's final content claiming success must not flip step.success
    to True when AgentSession reports unresolved failing tools (review N5:
    structured signal, not string prefix)."""
    plan_json = '{"steps": [{"title": "only", "details": "x"}]}'
    responses = [
        plan_json,
        '{"type":"tool_call","tool":"fake_run","args":{}}',  # sub iter 1
        '{"type":"final","content":"all good"}',             # iter 2 — blocked
        '{"type":"final","content":"still done"}',           # iter 3 — blocked
        '{"type":"final","content":"finished"}',             # iter 4 — blocked
        '{"type":"final","content":"final answer succeeded"}',  # iter 5 — accepted
        "merge report",
    ]
    coordinator, _ = _coordinator(tmp_path, responses, tools=[_FailingTool()])
    result = coordinator.run("g")

    assert len(result.step_results) == 1
    step = result.step_results[0]
    assert "succeeded" in step.summary
    assert not step.success
    assert not result.success
