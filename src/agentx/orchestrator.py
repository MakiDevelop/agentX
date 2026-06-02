from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentx.config import Settings
from agentx.json_repair import extract_json_object
from agentx.loop import AgentLoop
from agentx.memory_hall import MemoryHallClient
from agentx.runtime_prompt import PLANNING_SYSTEM_PROMPT, build_worker_system_prompt
from agentx.tools import ToolRegistry


@dataclass
class SubtaskResult:
    subtask_id: str
    description: str
    status: str  # "done" | "failed"
    result: str
    entry_id: str = ""


@dataclass
class OrchestratorResult:
    run_id: str
    goal: str
    subtask_results: list[SubtaskResult] = field(default_factory=list)
    summary: str = ""
    plan_entry_id: str = ""

    @property
    def success(self) -> bool:
        return all(r.status == "done" for r in self.subtask_results)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        llm: Any,
        memory: MemoryHallClient,
        tools: ToolRegistry,
        *,
        worker_max_steps: int | None = None,
        max_retries: int = 1,
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.memory = memory
        self.tools = tools
        self.worker_max_steps = worker_max_steps or int(os.getenv("AGENTX_ORCHESTRATOR_WORKER_STEPS", "8"))
        self.max_retries = max_retries
        self.trace = trace

    def run(self, prompt: str, namespace: str = "project:agentX") -> OrchestratorResult:
        run_id = f"run-{int(time.time())}"
        orch_ns = f"orchestration:{run_id}"
        self._trace(f"orchestrator start run_id={run_id}")

        # Phase 1: Plan
        plan = self._plan(prompt)
        if plan is None:
            self._trace("plan failed, falling back to single agent")
            return self._fallback_single_agent(prompt, namespace, run_id)

        goal = plan.get("goal", prompt[:100])
        subtasks = plan.get("subtasks", [])
        if not subtasks:
            self._trace("no subtasks in plan, falling back")
            return self._fallback_single_agent(prompt, namespace, run_id)

        self._trace(f"plan ok: goal={goal}, subtasks={len(subtasks)}")

        # Store plan in Memory Hall
        plan_entry_id = self._mh_write(
            content=json.dumps(plan, ensure_ascii=False),
            namespace=orch_ns,
            entry_type="plan",
            summary=f"Plan: {goal[:120]}",
            tags=["orchestration", "plan"],
            metadata={"run_id": run_id, "original_prompt": prompt[:500], "subtask_count": len(subtasks)},
        )

        # Store individual subtasks
        subtask_entries: dict[str, str] = {}
        for st in subtasks:
            sid = st["id"]
            entry_id = self._mh_write(
                content=json.dumps(st, ensure_ascii=False),
                namespace=orch_ns,
                entry_type="subtask",
                summary=st.get("description", "")[:120],
                tags=["orchestration", "subtask", f"subtask:{sid}"],
                metadata={"run_id": run_id, "subtask_id": sid, "status": "pending"},
                references=[plan_entry_id] if plan_entry_id else [],
            )
            subtask_entries[sid] = entry_id

        # Phase 2: Topological sort
        ordered = self._topo_sort(subtasks)
        self._trace(f"execution order: {[s['id'] for s in ordered]}")

        # Phase 3: Execute workers with build verification
        result = OrchestratorResult(run_id=run_id, goal=goal, plan_entry_id=plan_entry_id)
        completed_results: dict[str, str] = {}  # subtask_id -> result text

        # Snapshot: build state before any workers run
        pre_build = self._run_build_check()
        self._trace(f"pre-build: {'pass' if pre_build[0] else 'fail'}")

        for st in ordered:
            sid = st["id"]
            desc = st.get("description", "")
            depends = st.get("depends_on", [])
            hints = st.get("context_hints", [])

            # Build dependency context from verified results only
            dep_context = ""
            for dep_id in depends:
                if dep_id in completed_results:
                    dep_context += f"\n[{dep_id} result]: {completed_results[dep_id][:500]}\n"
            if hints:
                dep_context += "\nRelevant files: " + ", ".join(hints)

            # Execute worker
            self._trace(f"worker start: {sid} - {desc[:60]}")
            worker_answer = self._run_worker(desc, dep_context)

            # Verify: run build check AFTER worker to see if it actually changed anything
            post_build = self._run_build_check()
            build_passed = post_build[0]
            build_output = post_build[1]

            # Determine real status based on build check, not model's self-report
            if build_passed:
                status = "done"
                verified = "build_pass"
            else:
                # Build failed — try retry once
                if self.max_retries > 0:
                    self._trace(f"worker {sid} build failed, retrying with error")
                    retry_ctx = (
                        f"{dep_context}\n\n"
                        f"上一次嘗試後 build check 失敗:\n{build_output[:300]}\n"
                        f"請修正問題。"
                    )
                    worker_answer = self._run_worker(desc, retry_ctx)
                    post_build = self._run_build_check()
                    build_passed = post_build[0]
                    build_output = post_build[1]

                status = "done" if build_passed else "failed"
                verified = "build_pass" if build_passed else "build_fail"

            self._trace(f"worker done: {sid} status={status} verified={verified}")
            completed_results[sid] = worker_answer or ""

            # Store result with actual build output — not just model summary
            result_content = (
                f"Worker answer:\n{worker_answer or 'no output'}\n\n"
                f"Build verification: {verified}\n{build_output[:500]}"
            )
            result_entry_id = self._mh_write(
                content=result_content,
                namespace=orch_ns,
                entry_type="result",
                summary=f"[{sid}] {status} ({verified}): {desc[:60]}",
                tags=["orchestration", "result", f"subtask:{sid}", f"verified:{verified}"],
                metadata={
                    "run_id": run_id,
                    "subtask_id": sid,
                    "status": status,
                    "verified": verified,
                    "build_output": build_output[:200],
                },
                references=[subtask_entries.get(sid, "")],
            )

            result.subtask_results.append(SubtaskResult(
                subtask_id=sid,
                description=desc,
                status=status,
                result=worker_answer or "",
                entry_id=result_entry_id,
            ))

        # Phase 4: Final integration build check
        final_build = self._run_build_check()
        final_passed = final_build[0]
        final_output = final_build[1]
        self._trace(f"final build: {'pass' if final_passed else 'FAIL'}")

        # Phase 5: Summarize with real data
        done = sum(1 for r in result.subtask_results if r.status == "done")
        failed = sum(1 for r in result.subtask_results if r.status == "failed")
        total = len(result.subtask_results)

        summary_parts = [
            f"目標：{goal}",
            f"完成：{done}/{total}",
        ]
        if failed:
            summary_parts.append(f"失敗：{failed}")
        summary_parts.append(f"最終 build：{'✅ pass' if final_passed else '❌ FAIL'}")
        summary_parts.append("")

        for r in result.subtask_results:
            icon = "✅" if r.status == "done" else "❌"
            summary_parts.append(f"{icon} [{r.subtask_id}] {r.description}")
            if r.result:
                preview = "\n".join(r.result.strip().splitlines()[:2])
                summary_parts.append(f"   → {preview}")

        if not final_passed:
            summary_parts.append("")
            summary_parts.append(f"Build error:\n{final_output[:300]}")

        summary_parts.append("")
        result.summary = "\n".join(summary_parts)

        self._mh_write(
            content=result.summary + f"\n\nFinal build output:\n{final_output[:500]}",
            namespace=orch_ns,
            entry_type="summary",
            summary=f"Orchestration: {done}/{total} done, build={'pass' if final_passed else 'FAIL'}",
            tags=["orchestration", "summary", f"build:{'pass' if final_passed else 'fail'}"],
            metadata={
                "run_id": run_id,
                "completed": done,
                "failed": failed,
                "total": total,
                "final_build_pass": final_passed,
                "final_build_output": final_output[:300],
            },
            references=[plan_entry_id] + [r.entry_id for r in result.subtask_results if r.entry_id],
        )

        self._trace(f"orchestrator done: {done}/{total} completed, build={'pass' if final_passed else 'FAIL'}")
        return result

    def _plan(self, prompt: str) -> dict[str, Any] | None:
        """Use LLM to decompose prompt into a structured plan."""
        plan_settings = self.settings.with_updates(max_steps=6)
        planner = AgentLoop(
            settings=plan_settings,
            ollama=self.llm,
            tools=self.tools,
            system_prompt=PLANNING_SYSTEM_PROMPT,
            trace=self.trace,
        )
        try:
            raw = planner.run(f"請將以下任務拆解成子任務：\n{prompt}")
        except Exception as e:
            self._trace(f"plan error: {e}")
            return None

        # Try to extract plan JSON from the response
        data = extract_json_object(raw)
        if data and "subtasks" in data:
            return data

        # The model might have wrapped the plan in the final answer content
        content = data.get("content", raw) if data else raw
        if isinstance(content, str):
            inner = extract_json_object(content)
            if inner and "subtasks" in inner:
                return inner

        self._trace(f"plan parse failed: {raw[:200]}")
        return None

    def _run_worker(self, subtask_description: str, dependency_context: str) -> str:
        """Spawn a fresh AgentSession for a single subtask."""
        worker_settings = self.settings.with_updates(max_steps=self.worker_max_steps)
        system_prompt = build_worker_system_prompt(subtask_description, dependency_context)

        worker = AgentLoop(
            settings=worker_settings,
            ollama=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            trace=self.trace,
        )
        try:
            return worker.run(subtask_description)
        except Exception as e:
            self._trace(f"worker error: {e}")
            return f"Worker 執行失敗: {e}"

    def _fallback_single_agent(self, prompt: str, namespace: str, run_id: str) -> OrchestratorResult:
        """Fallback: run as single agent when planning fails."""
        self._trace("running fallback single agent")
        worker = AgentLoop(
            settings=self.settings,
            ollama=self.llm,
            tools=self.tools,
            trace=self.trace,
        )
        try:
            answer = worker.run(prompt, namespace=namespace)
        except Exception as e:
            answer = f"執行失敗: {e}"

        result = OrchestratorResult(
            run_id=run_id,
            goal=prompt[:100],
            subtask_results=[SubtaskResult(
                subtask_id="fallback",
                description=prompt[:200],
                status="done",
                result=answer,
            )],
            summary=answer,
        )
        return result

    def _mh_write(self, **kwargs: Any) -> str:
        """Write to Memory Hall, return entry_id. Fail silently."""
        refs = kwargs.pop("references", None) or []
        kwargs["references"] = [r for r in refs if r]  # filter empty
        try:
            resp = self.memory.write_structured(**kwargs)
            return resp.get("entry_id", "")
        except Exception as e:
            self._trace(f"memory hall write failed: {e}")
            return ""

    def _run_build_check(self) -> tuple[bool, str]:
        """Run project-appropriate build check. Returns (passed, output)."""
        ws = self.settings.workspace
        if (ws / "Cargo.toml").exists():
            cmd = ["cargo", "check"]
        elif (ws / "go.mod").exists():
            cmd = ["go", "build", "./..."]
        elif (ws / "package.json").exists():
            cmd = ["npm", "run", "build"]
        elif (ws / "pyproject.toml").exists():
            cmd = ["uv", "run", "ruff", "check", "."]
        else:
            return True, "no build system detected"

        try:
            completed = subprocess.run(
                cmd, cwd=ws, text=True, capture_output=True, timeout=60, check=False,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()
            return completed.returncode == 0, output
        except Exception as e:
            return False, f"build check error: {e}"

    def _topo_sort(self, subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Topological sort by depends_on. Falls back to original order on cycles."""
        by_id = {s["id"]: s for s in subtasks}
        visited: set[str] = set()
        result: list[dict[str, Any]] = []

        def visit(sid: str, path: set[str]) -> bool:
            if sid in path:
                return False  # cycle
            if sid in visited:
                return True
            path.add(sid)
            st = by_id.get(sid)
            if st is None:
                return True
            for dep in st.get("depends_on", []):
                if not visit(dep, path):
                    return False
            path.discard(sid)
            visited.add(sid)
            result.append(st)
            return True

        for s in subtasks:
            if not visit(s["id"], set()):
                return subtasks  # cycle detected, use original order

        return result

    def _trace(self, message: str) -> None:
        if self.trace is not None:
            self.trace(f"[orch] {message}")
