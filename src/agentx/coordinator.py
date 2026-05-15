"""Plan-then-execute coordinator.

Decomposes a goal into ordered sub-tasks, runs each in a fresh AgentSession
(clean context per sub-task), collects summaries, then merges into a final
report. Designed for tasks too big for a single agent session: each sub-task's
context stays focused, and failure dumps from one step don't pollute the next.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from agentx.config import Settings
from agentx.hooks import HookManager
from agentx.json_repair import extract_json_object
from agentx.loop import AgentSession
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.tools import ToolRegistry


PLAN_SYSTEM_PROMPT = """你是 agentX 的計畫員。

收到一個目標，請拆成有序的子任務。每個子任務必須：
- 自足：另一個 agent 拿到「目標 + 目前已完成子任務摘要 + 該子任務描述」即可獨立執行
- 具體：1–2 句說清楚要做什麼，必要時提到要建立／修改的具體檔案或指令
- 有序：先決條件先做（例如建檔在驗證之前、寫主程式在寫測試之前）

回傳嚴格 JSON：
{"steps": [{"title": "短標題", "details": "具體要做的事"}, ...]}

子任務數量：3–7 之間最佳。太多步浪費 turn，太少則每步壓力過大。
最後一個子任務通常是「驗證 + 修正」型，給 agent 自我檢驗的空間。
"""


MERGE_SYSTEM_PROMPT = """你是 agentX 的整合員。

收到目標、計畫、與每個子任務的執行摘要後，請用繁體中文輸出最終報告：
- 明確說整體目標是否達成（成功／失敗／部分成功）
- 列出每一步的結果（一行一步）
- 若有未解決的失敗，具體寫出最後一次錯誤訊息與卡點，不要含糊

禁止：宣稱成功但實際有步驟失敗；使用 Markdown 標題／粗體／表格。
輸出風格：純文字、條列用「- 」開頭即可。
"""


class PlanStep(BaseModel):
    title: str
    details: str = ""


class Plan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)


@dataclass
class StepResult:
    step: PlanStep
    summary: str
    success: bool


@dataclass
class CoordinatorResult:
    plan: Plan
    step_results: list[StepResult] = field(default_factory=list)
    final: str = ""
    success: bool = False


class CoordinatorError(RuntimeError):
    """Raised when planning produces unusable output."""


class Coordinator:
    def __init__(
        self,
        settings: Settings,
        ollama: OllamaClient,
        tools: ToolRegistry,
        memory: MemoryHallClient,
        namespace: str = "project:agentX",
        trace: Callable[[str], None] | None = None,
        hooks: HookManager | None = None,
    ) -> None:
        self.settings = settings
        self.ollama = ollama
        self.tools = tools
        self.memory = memory
        self.namespace = namespace
        self.trace = trace
        self.hooks = hooks

    def run(self, goal: str) -> CoordinatorResult:
        plan = self._plan(goal)
        self._emit_trace(f"plan with {len(plan.steps)} steps")
        results: list[StepResult] = []
        for index, step in enumerate(plan.steps, start=1):
            self._emit_trace(f"step {index}/{len(plan.steps)}: {step.title}")
            result = self._execute_step(goal, plan, step, results)
            results.append(result)
            self._emit_trace(
                f"step {index} done ok={result.success} summary={result.summary[:120]!r}"
            )
        final = self._merge(goal, plan, results) if results else "(plan was empty)"
        success = bool(results) and all(r.success for r in results)
        return CoordinatorResult(plan=plan, step_results=results, final=final, success=success)

    def _plan(self, goal: str) -> Plan:
        messages = [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": f"目標：\n{goal}\n\n只回 JSON。"},
        ]
        raw = self.ollama.chat(messages, json_mode=True)
        data = extract_json_object(raw)
        if data is None:
            raise CoordinatorError(f"plan response was not JSON: {raw[:200]!r}")
        try:
            return Plan.model_validate(data)
        except ValidationError as exc:
            raise CoordinatorError(f"plan JSON invalid: {exc}") from exc

    def _execute_step(
        self,
        goal: str,
        plan: Plan,
        step: PlanStep,
        completed: list[StepResult],
    ) -> StepResult:
        session = AgentSession(
            settings=self.settings,
            ollama=self.ollama,
            tools=self.tools,
            memory=self.memory,
            namespace=self.namespace,
            trace=self.trace,
            hooks=self.hooks,
        )
        completed_block = (
            "\n".join(
                f"- {r.step.title}（成功={r.success}）：{_truncate(r.summary, 240)}"
                for r in completed
            )
            or "（尚未有完成的子任務）"
        )
        upcoming_block = "\n".join(
            f"  {i}. {s.title}" for i, s in enumerate(plan.steps, start=1)
        )
        prompt = (
            f"整體目標：\n{goal}\n\n"
            f"完整計畫：\n{upcoming_block}\n\n"
            f"已完成的子任務摘要：\n{completed_block}\n\n"
            f"目前的子任務：\n"
            f"  標題：{step.title}\n"
            f"  細節：{step.details}\n\n"
            "只執行這個子任務，不要做下個任務的事。完成後用 type=final 回覆 200 字內的摘要，"
            "說明你做了什麼、是否成功、若失敗最後一次錯誤是什麼。"
        )
        summary = session.ask(prompt, namespace=self.namespace)
        # Structured success: model must have hit a clean final answer AND no
        # tool result was left in a failed state. String prefixes on the
        # summary are unreliable (review N5).
        success = (
            session.last_termination == "final"
            and not session.last_failing_tools
        )
        return StepResult(step=step, summary=summary, success=success)

    def _merge(self, goal: str, plan: Plan, results: list[StepResult]) -> str:
        results_block = "\n\n".join(
            f"步驟 {i}/{len(results)}：{r.step.title}\n"
            f"成功={r.success}\n摘要：{_truncate(r.summary, 800)}"
            for i, r in enumerate(results, start=1)
        )
        plan_block = "\n".join(
            f"  {i}. {s.title}" for i, s in enumerate(plan.steps, start=1)
        )
        messages = [
            {"role": "system", "content": MERGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"原始目標：\n{goal}\n\n"
                    f"計畫（共 {len(plan.steps)} 步）：\n{plan_block}\n\n"
                    f"各步驟結果：\n{results_block}\n\n"
                    "請給最終報告。"
                ),
            },
        ]
        return self.ollama.chat(messages, json_mode=False).strip()

    def _emit_trace(self, message: str) -> None:
        if self.trace is not None:
            self.trace(f"[coordinator] {message}")


def _truncate(text: str, limit: int) -> str:
    cleaned = text.replace("\n", " ")
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


__all__ = [
    "Coordinator",
    "CoordinatorError",
    "CoordinatorResult",
    "Plan",
    "PlanStep",
    "StepResult",
]
