from __future__ import annotations

import re
import threading
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from dataclasses import asdict

from pydantic import ValidationError

from agentx.bootstrap import build_memory_context, build_repo_context
from agentx.config import Settings
from agentx.context_compactor import ContextCompactor, HeuristicContextCompactor, LLMContextCompactor
from agentx.recovery import RecoveryPlaybook
from agentx.json_repair import extract_json_object
from agentx.ollama import OllamaClient
from agentx.errors import ErrorContext, ErrorType, RecoverySuggestion
from agentx.error_classifier import ErrorClassifier
from agentx.protocol import FinalAnswer, Reflect, ToolCall, ToolResult
from agentx.runtime_prompt import build_agent_system_prompt
from agentx.tasks import format_task_list_summary, get_next_task_id, load_tasks, save_tasks
from agentx.hooks import (
    HookEvent,
    HookManager,
    HookResult,
    SessionStartContext,
    SessionEndContext,
    FinalAnswerContext,
    TurnStartContext,
    TurnEndContext,
    CompactContext,
    ErrorHookContext,
    ToolResultContext,
)
from agentx.memory_hall import MemoryHallClient
from agentx.tools import ToolRegistry
from agentx.learning import load_learning_manager, LearningManager
from agentx.session_store import SessionStore

EDITING_TOOLS = {"edit_file", "write_file", "search_replace", "insert_code", "apply_patch"}


class AgentLoop:
    def __init__(
        self,
        settings: Settings,
        ollama: OllamaClient,
        tools: ToolRegistry,
        namespace: str = "project:agentX",
        trace: Callable[[str], None] | None = None,
        system_prompt: str | None = None,
        compactor: ContextCompactor | None = None,
        memory: MemoryHallClient | None = None,
        hooks: HookManager | None = None,
    ) -> None:
        self.session = AgentSession(
            settings=settings,
            ollama=ollama,
            tools=tools,
            namespace=namespace,
            trace=trace,
            system_prompt=system_prompt,
            compactor=compactor,
            memory=memory,
            hooks=hooks,
        )

    def run(
        self,
        prompt: str,
        namespace: str = "project:agentX",
        cancel_event: threading.Event | None = None,
        plan_only: bool | None = None,
    ) -> str:
        return self.session.ask(
            prompt, namespace=namespace, cancel_event=cancel_event, plan_only=plan_only
        )


class AgentSession:
    def __init__(
        self,
        settings: Settings,
        ollama: OllamaClient,
        tools: ToolRegistry,
        namespace: str = "project:agentX",
        trace: Callable[[str], None] | None = None,
        system_prompt: str | None = None,
        compactor: ContextCompactor | None = None,
        memory: MemoryHallClient | None = None,
        hooks: HookManager | None = None,
    ) -> None:
        self.settings = settings
        self.ollama = ollama
        self.tools = tools
        self.namespace = namespace
        self.trace = trace
        self.compaction_count = 0
        self.plan_only: bool = False
        self._custom_system_prompt = system_prompt
        self._has_completed_planning: bool = False
        self.memory = memory
        self.hooks = hooks
        self.learning_manager: LearningManager = load_learning_manager(settings, memory)
        self.consecutive_reflections: int = 0
        self.max_consecutive_reflections: int = 3
        self.learning_enabled = getattr(settings, "learning_enabled", True)
        if self.learning_enabled:
            if self.hooks is None:
                self.hooks = HookManager()
            # Codex feedback: avoid fragile `cb is bound_method` checks (bound method identity
            # is not stable across sessions / shared HookManager). Use a simple guard flag instead.
            if not getattr(self, "_learning_hooks_registered", False):
                self.hooks.add(HookEvent.FINAL_ANSWER, self._on_final_answer_learning)
                self.hooks.add(HookEvent.SESSION_END, self._on_session_end_learning)
                self._learning_hooks_registered = True
        if self.hooks is not None:
            self.tools.hooks = self.hooks
            # Hook-driven verify: POST_TOOL_USE populates pending_verifies (stateful, persisted),
            # provides targeted verify context via additional_context. Guard against duplicate reg
            # (like learning hooks) in case HookManager is reused across sessions.
            if not getattr(self, "_post_edit_verify_registered", False):
                self.hooks.add(HookEvent.POST_TOOL_USE, self._on_post_edit_verify)
                self._post_edit_verify_registered = True

        # Task List 持久化載入（Micro-task 21 A2）
        self.tasks: list[dict] = load_tasks(self.settings.workspace)

        # 錯誤恢復相關狀態（階段一）
        self.error_classifier = ErrorClassifier()
        self.error_history: list[ErrorContext] = []
        self.current_error: ErrorContext | None = None

        # Context Compaction v2（Phase B1）
        if compactor is not None:
            self.compactor: ContextCompactor = compactor
        elif "gemma" in settings.model.lower():
            # Opt-in LLM-assisted for Gemma4/small models (smarter summary using the model itself)
            self.compactor: ContextCompactor = LLMContextCompactor(self.ollama)
        else:
            self.compactor: ContextCompactor = HeuristicContextCompactor()

        # Phase B2：錯誤恢復策略成熟化
        self.recovery_playbook = RecoveryPlaybook()

        # === Safety hardening states (continued from feature/agent-tools review N series) ===
        # Outcome of the most recent ask() — coordinator / callers consume these
        # for structured success judgment (review N5: don't rely on string
        # prefixes of the summary).
        self.last_termination: str = "unknown"
        self.last_failing_tools: set[str] = set()
        self.pending_verifies: set[str] = set()  # hook-driven edit-verify state (next slice)
        # Hysteresis state for auto-compact (review N8: don't re-compact every
        # turn when bootstrap alone is over threshold).
        self._last_compact_tokens: int | None = None
        # Persistent per-tool outcome tracker. Updated on every _run_tool;
        # later success of the same tool clears its failed state. Survives
        # compact() (which empties messages but not session-level state)
        # but is reset by clear(). (review codex C3: 12-message window was
        # too narrow — a long sequence of read_file / search_text after a
        # failed cargo test would make the failure "fall off" and let the
        # finalization guard pass a lying success.)
        self._tool_outcomes: dict[str, bool] = {}
        self._file_ops: dict[str, set[str]] = {}
        self._final_guard_retries: int = 0
        self._session_store: SessionStore | None = None

        self.messages = self._initial_messages()

    def reflect_and_learn(self, transcript_summary: str | None = None) -> list[dict]:
        """Trigger self-learning reflection. Generates proposals (never auto-applies core changes).
        This is how agentX gets 'smarter' over time while respecting human gate + fidelity.
        Call after ask() or on /learn.
        """
        if not self.learning_enabled:
            return []

        # Gather context
        recent_messages = self.messages[-20:] if self.messages else []
        transcript = transcript_summary or "\n".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:500]}" for m in recent_messages
        )
        errors = []
        for e in self.error_history[-5:]:
            if hasattr(e, '__dataclass_fields__'):
                d = asdict(e)
                errors.append({k: str(v) for k, v in d.items()})
            else:
                errors.append(str(e))
        tasks_summary = [{"id": t.get("id"), "status": t.get("status"), "title": t.get("title")} for t in (self.tasks or [])[-5:]]

        # Load key principles from AGENTX.md for fitness (simple read; agent can do deeper)
        principles = ""
        agentyx_path = self.settings.workspace / "AGENTX.md"
        if agentyx_path.exists():
            principles = agentyx_path.read_text(encoding="utf-8", errors="replace")[:4000]

        proposals = self.learning_manager.reflect_on_session(
            self.ollama,
            transcript,
            errors,
            tasks_summary,
            principles or "Follow safety, MT22 tasks as truth, kernel/substrate decoupling, proposal-only for core changes."
        )

        # Record as learning episode if memory
        if self.memory and proposals:
            try:
                summary = f"Self-learning proposals from session: {len(proposals)} new. Titles: {[p.title for p in proposals]}"
                self.memory.write(summary, namespace=self.namespace)
            except Exception:
                pass

        return [{"id": p.id, "title": p.title, "type": p.lesson_type, "status": p.status} for p in proposals]

    def _on_final_answer_learning(self, ctx: FinalAnswerContext) -> None:
        if ctx.plan_only:
            return
        try:
            learnings = self.reflect_and_learn()
            if learnings:
                self._emit_trace(
                    f"[learning] Generated {len(learnings)} proposals. "
                    "Review with /learn or .agentx/learning/proposals/"
                )
        except Exception as e:
            self._emit_trace(f"[learning] Reflection skipped due to error: {e}")

    def _on_session_end_learning(self, ctx: SessionEndContext) -> None:
        if ctx.termination != "max_steps_exceeded":
            return
        try:
            self.reflect_and_learn("session ended without final answer (max_steps reached)")
        except Exception:
            pass

    _RESTORE_SENTINEL = "__restore__"

    def _initial_messages(self) -> list[dict[str, str]]:
        if self._custom_system_prompt == self._RESTORE_SENTINEL:
            return [{"role": "system", "content": "(session restored from store)"}]
        system_prompt = self._custom_system_prompt or build_agent_system_prompt(self.settings.persona, tools=self.tools, model=self.settings.model)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": "Repo bootstrap context:\n" + build_repo_context(self.settings.workspace)},
            {
                "role": "system",
                "content": "Memory Hall context:\n"
                + (
                    build_memory_context(
                        self.memory or getattr(self.tools, "memory", None),
                        project_namespace=self.namespace,
                        query=f"{self.settings.workspace.name} project context",
                    )
                    if (self.memory or getattr(self.tools, "memory", None)) is not None
                    else "(Memory Hall client not provided)"
                ),
            },
        ]

    def enable_persistence(self, workspace: Path | None = None) -> None:
        ws = workspace or self.settings.workspace
        self._session_store = SessionStore.create(ws, self.settings.model, self.namespace)
        for msg in self.messages:
            self._session_store.append(msg["role"], msg["content"])
        # Snapshot current important state at enable time
        self._persist_state_event("tool_outcomes", dict(self._tool_outcomes))
        self._persist_state_event("file_ops", {k: list(v) for k, v in self._file_ops.items()})
        self._persist_state_event("last_failing_tools", list(self.last_failing_tools))
        self._persist_state_event("compaction_count", self.compaction_count)
        self._persist_state_event("pending_verifies", list(self.pending_verifies))

    def _persist_message(self, role: str, content: str, **metadata: Any) -> None:
        if self._session_store is not None:
            self._session_store.append(role, content, metadata=metadata or None)

    def _persist_state_event(self, name: str, data: dict[str, Any]) -> None:
        """Persist a snapshot of important session state so resume can reconstruct
        more than messages (e.g. tool outcomes for final guard, file ops for the pillar).
        """
        if self._session_store is not None:
            self._session_store.append_state(name, data)

    def _restore_state_event(self, name: str, data: dict[str, Any]) -> None:
        if name == "tool_outcomes":
            self._tool_outcomes = {k: bool(v) for k, v in (data or {}).items()}
        elif name == "file_ops":
            self._file_ops = {k: set(v) if isinstance(v, (list, tuple)) else set() for k, v in (data or {}).items()}
        elif name == "last_failing_tools":
            self.last_failing_tools = set(data or [])
        elif name == "compaction_count":
            try:
                self.compaction_count = int(data)
            except (TypeError, ValueError):
                pass
        # last_termination etc. can be added later if needed; start minimal for Codex item
        elif name == "pending_verifies":
            self.pending_verifies = set(data or [])

    def _on_post_edit_verify(self, ctx: ToolResultContext) -> HookResult | None:
        """Hook-driven post-edit verify listener (POST_TOOL_USE).
        - Stateful: track paths in pending_verifies + persist via state event (for resume/compact).
        - Targeted: suggest ruff on specific path (instead of always full run_tests).
        - Injects verify guidance via additional_context (appears in tool result to model).
        This moves the previous hardcoded verify_msg (loop ~492) to hook for extensibility.
        """
        # Normalize for aliases (registry canonicalizes search_replace -> edit_file primary for ctx.tool)
        tool = ctx.tool
        if tool == "search_replace":
            tool = "edit_file"
        if tool not in EDITING_TOOLS or not ctx.result.ok:
            return None
        path = str((ctx.args or {}).get("path", "")) if ctx.args else ""
        if not path:
            return None
        self.pending_verifies.add(path)
        self._persist_state_event("pending_verifies", list(self.pending_verifies))
        # Provide targeted verify context (will be appended to tool result content by registry POST)
        # Updated message to match current slice behavior (auto test + clear after), resolving model contradiction.
        verify_ctx = (
            f"【Hook-driven verify - stateful】{ctx.tool} on {path} succeeded. "
            "Path added to pending_verifies (persisted for resume/compact). "
            "In this slice, full run_tests will auto-run next and pending cleared after the batch. "
            f"For more targeted: read_file key region + consider `uv run ruff check {path}`. "
            "Do not skip for Gemma4 reliability."
        )
        return HookResult(additional_context=verify_ctx)

    @classmethod
    def from_session_store(
        cls,
        store_path: Path,
        settings: "Settings",
        ollama: Any,
        tools: "ToolRegistry",
        **kwargs: Any,
    ) -> "AgentSession":
        store = SessionStore.load(store_path)
        kwargs.setdefault("system_prompt", cls._RESTORE_SENTINEL)
        session = cls(settings=settings, ollama=ollama, tools=tools, **kwargs)
        session.messages = store.replay()
        session._session_store = store
        # Restore state snapshots (Codex medium item addressed).
        for name, data in store.replay_states():
            session._restore_state_event(name, data)
        return session

    def ask(
        self,
        prompt: str,
        namespace: str = "project:agentX",
        cancel_event: threading.Event | None = None,
        plan_only: bool | None = None,
    ) -> str:
        effective_plan_only = plan_only if plan_only is not None else self.plan_only

        direct = self._direct_tool_call(prompt)
        if direct is not None:
            result = self._run_tool(direct)
            self.messages.append(
                {
                    "role": "user",
                    "content": f"Task: {prompt}",
                }
            )
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})
            if self.hooks:
                self.hooks.fire(HookEvent.SESSION_END, SessionEndContext(
                    namespace=self.namespace,
                    termination="direct_tool",
                    message_count=len(self.messages),
                    error_count=len(self.error_history),
                ))
            if result.ok:
                return result.content
            return f"工具執行失敗：{result.content}"

        user_content = (
            f"Workspace: {self.settings.workspace}\n"
            f"Default memory namespace: {namespace}\n"
            f"Task: {prompt}"
        )
        self.messages.append({"role": "user", "content": user_content})
        self._persist_message("user", user_content)

        if self.hooks:
            self.hooks.fire(HookEvent.SESSION_START, SessionStartContext(
                namespace=namespace, prompt=prompt,
            ))

        for step in range(self.settings.max_steps):
            self._maybe_auto_compact()

            if self.hooks:
                self.hooks.fire(HookEvent.TURN_START, TurnStartContext(
                    step=step, message_count=len(self.messages),
                    tokens_estimate=self.context_tokens_estimate,
                ))

            raw = self.ollama.chat(self.messages, json_mode=True, cancel_event=cancel_event)
            action = self._parse_action(raw)
            if isinstance(action, InvalidAction):
                self.messages.append({"role": "assistant", "content": raw})
                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Invalid response. Return strict JSON only. "
                            "To inspect files, call a real tool like "
                            '{"type":"tool_call","tool":"list_files","args":{"path":"."}}. '
                            'To finish, return {"type":"final","content":"..."}'
                        ),
                    }
                )
                continue
            if isinstance(action, FinalAnswer):
                failing = self._unresolved_failing_tools()
                if failing:
                    self._final_guard_retries += 1
                    if self._final_guard_retries >= 4:
                        self.last_failing_tools = failing
                        return self._handle_final_answer(
                            f"任務失敗：工具 {', '.join(sorted(failing))} 仍有未解決的錯誤。"
                            f" 模型原始回覆: {action.content}",
                            effective_plan_only,
                        )
                    blocked_content = action.model_dump_json()
                    guard_msg = (
                        f"FinalAnswer 被擋：工具 {', '.join(sorted(failing))} 仍有未解決的錯誤。"
                        "請先修復錯誤再提交最終答案。"
                    )
                    self.messages.append({"role": "assistant", "content": blocked_content})
                    self.messages.append({"role": "system", "content": guard_msg})
                    self._persist_message("assistant", blocked_content)
                    self._persist_message("system", guard_msg)
                    continue
                self._final_guard_retries = 0
                return self._handle_final_answer(action.content, effective_plan_only)

            if isinstance(action, Reflect):
                self.consecutive_reflections += 1
                reflection = self._reflect(action.focus)
                reflect_content = action.model_dump_json()
                reflect_system = f"=== Reflection ===\n{reflection}"
                self.messages.append({"role": "assistant", "content": reflect_content})
                self.messages.append({"role": "system", "content": reflect_system})
                self._persist_message("assistant", reflect_content)
                self._persist_message("system", reflect_system)
                if effective_plan_only:
                    self._has_completed_planning = True

                # Micro-task 20: Reflection loop guard
                if self.consecutive_reflections >= self.max_consecutive_reflections:
                    if effective_plan_only:
                        guard_msg = (
                            f"【Reflection Loop Guard 觸發 - PLAN MODE】\n"
                            f"你已連續 {self.consecutive_reflections} 次輸出 reflect 而未產出 final 方案。\n"
                            "plan mode 的目的是產生高品質規劃，請立即：\n"
                            "- 使用 task_list 整理狀態\n"
                            "- 輸出一個結構化、完整的 final 方案（清楚列出步驟、風險、驗證方式）\n"
                            "- 不要再純粹 Reflection，也不要建議執行工具（plan mode 禁止）\n\n"
                            "（Gemma4 等弱模型特別容易陷入無效 reflection，guard 強制你產出可執行規劃。）\n"
                            "強制進度，停止無效迴圈。guard 已重置。"
                        )
                    else:
                        guard_msg = (
                            f"【Reflection Loop Guard 觸發】\n"
                            f"你已連續 {self.consecutive_reflections} 次輸出 reflect 而未執行實質工具或 final。\n"
                            "在 headless 模式中這會導致效率低下、token 浪費與無效迴圈。\n\n"
                            "請立即採取行動：\n"
                            "- 使用 task_list 快速整理目前所有任務狀態\n"
                            "- 輸出一個有價值的 final 方案（即使不完美也先給出可執行建議）\n"
                            "- 或執行下一個具體的工具行動（search_replace / run_tests 等）\n\n"
                            "（Gemma4 等小模型容易過度 reflection 導致 token 燒盡，guard 保護你專注執行。）\n"
                            "強制進度，停止純粹 Reflection。guard 已重置。"
                        )
                    self.messages.append({"role": "system", "content": guard_msg})
                    self.consecutive_reflections = 0  # give one more chance after warning
                continue

            if effective_plan_only and not self._has_completed_planning:
                # Plan mode: require at least one reflection, and treat a good final plan as planning complete.
                self.messages.append({"role": "assistant", "content": action.model_dump_json()})

                if isinstance(action, FinalAnswer):
                    # Planning phase considered complete once a final plan is delivered.
                    # Subsequent turns (if any) can use tools.
                    self._has_completed_planning = True
                    # For plan-then-execute, we allow the model to continue into execution in the same session.
                    continue

                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你目前處於 PLAN MODE（Headless）。\n"
                            "請先進行認真的 Reflection，檢討你的規劃是否完整、風險是否清楚、驗證方式是否可行。\n"
                            "請用結構化方式思考步驟。\n\n"
                            "完成 Reflection 後，請明確判斷：\n"
                            "- 如果規劃還不夠好 → 繼續優化規劃並再次 Reflection\n"
                            "- 如果規劃已經完整且風險可控 → 在 final answer 中清楚輸出完整方案，並建議可以開始執行\n\n"
                            "請輸出 reflect 或 final。"
                        ),
                    }
                )
                continue

            # Special handling for internal task management tools
            if action.tool.startswith("task_"):
                result = self._handle_task_tool(action)
            else:
                result = self._run_tool(action)

            assistant_content = action.model_dump_json()
            tool_content = self._format_tool_result(result)
            self.messages.append({"role": "assistant", "content": assistant_content})
            self.messages.append({"role": "tool", "content": tool_content})
            self._persist_message("assistant", assistant_content)
            self._persist_message("tool", tool_content)

            if self.hooks:
                self.hooks.fire(HookEvent.TURN_END, TurnEndContext(
                    step=step, action_type="tool_call",
                    tool_name=action.tool, result_ok=result.ok,
                ))

            # === Opt5: 成功編輯模式主動寫入 Memory Hall 作為經驗庫（供未來 few-shot recall） ===
            # 讓 Gemma4 等模型可以從過去成功案例學到模式，增加「聰明」程度。
            # (verify injection moved to _on_post_edit_verify POST hook for stateful/targeted)
            if result.ok and action.tool in ("edit_file", "write_file", "search_replace", "insert_code", "apply_patch"):
                try:
                    path = action.args.get("path", "unknown")
                    lesson = f"成功 {action.tool} on {path}。結果摘要: {(result.content or '')[:400]}"
                    if hasattr(self.memory, "write_structured"):
                        self.memory.write_structured(
                            content=lesson,
                            namespace=self.namespace,
                            entry_type="success_pattern",
                            summary=f"成功 {action.tool} @{path}",
                            tags=["edit-success", "gemma-lesson", action.tool],
                            metadata={"tool": action.tool, "path": str(path)},
                        )
                    else:
                        self.memory.write(lesson, namespace=self.namespace)
                except Exception:
                    pass  # 靜默，不影響主流程

            # === 錯誤分類與基礎恢復處理（階段一 + 步驟 4） ===
            if not result.ok:
                if result.error_type:
                    try:
                        error_type = ErrorType(result.error_type)
                    except ValueError:
                        error_type = self.error_classifier.classify(action.tool, result)
                else:
                    error_type = self.error_classifier.classify(action.tool, result)
                self.current_error = ErrorContext(
                    error_type=error_type,
                    tool_name=action.tool,
                    error_message=result.content or "",
                )
                self.error_history.append(self.current_error)

                is_stuck = self._detect_stuck(self.current_error)
                if is_stuck:
                    self.current_error.error_type = ErrorType.STUCK
                    stuck_msg = self._build_stuck_intervention_message(self.current_error)
                    self.messages.append({"role": "system", "content": stuck_msg})
                    self.messages.append({
                        "role": "system",
                        "content": "請立即輸出 reflect，專注解決當前卡住的問題。"
                    })

                if self.hooks:
                    self.hooks.fire(HookEvent.ERROR, ErrorHookContext(
                        tool_name=action.tool, error_type=error_type.value,
                        error_message=result.content or "",
                        is_stuck=is_stuck,
                        error_history_length=len(self.error_history),
                    ))

                if is_stuck:
                    continue

                if error_type in (ErrorType.TRANSIENT, ErrorType.CALL_ERROR):
                    # 有限次重試引導
                    retry_guidance = self._build_retry_guidance(action.tool, result.content, error_type)
                    self.messages.append({"role": "system", "content": retry_guidance})
                else:
                    # 較嚴重錯誤 → 強烈引導進行結構化錯誤 Reflection
                    reflection_guidance = self._build_error_reflection_guidance(self.current_error)
                    self.messages.append({"role": "system", "content": reflection_guidance})

                    # 額外鼓勵模型主動輸出 reflect
                    self.messages.append({
                        "role": "system",
                        "content": "請現在輸出 reflect，專注分析這個錯誤並提出恢復策略。"
                    })

            else:
                self.current_error = None

            # Micro-task 20: reset reflection loop counter only on successful tool action
            # (failed tool + reflect 迴圈應被 guard 捕捉，避免逃脫)
            if result.ok:
                self.consecutive_reflections = 0

            # Micro-task 12：編輯工具成功後，自動執行測試（+ 條件式 Reflection）
            # Hook-driven update: pending_verifies populated by _on_post_edit_verify (POST hook).
            # Targeted verify encouraged via hook additional_context (ruff on path).
            # For this slice: clear pending after edit success; full run_tests kept for compat
            # (future: conditional targeted ruff per pending paths instead of always full).
            if action.tool in EDITING_TOOLS and result.ok:
                self._edit_count = getattr(self, "_edit_count", 0) + 1

                # 自動跑 build/test (full; hook provides targeted guidance in tool result)
                test_result = self.tools.run("run_tests", {})
                self.messages.append({"role": "tool", "content": self._format_tool_result(test_result)})

                # Clear hook-managed pending after the verification step (test batch) completes.
                # This makes pending stateful during the edit (for resume if interrupted) and
                # clears only after "verification" per the slice design. Updated hook message
                # reflects the auto behavior to avoid model contradiction.
                if self.pending_verifies:
                    self.pending_verifies.clear()
                    self._persist_state_event("pending_verifies", [])

                # 簡單編輯（累計 <=2 次）：只報告結果 + JSON 提醒，跳過重量級 reflection
                if self._edit_count <= 2:
                    build_status = "passed" if test_result.ok else "FAILED"
                    self.messages.append({
                        "role": "system",
                        "content": (
                            f"Build/test {build_status}. "
                            "Continue with the next action, or reply with "
                            '{"type":"final","content":"your summary"} if done.'
                        ),
                    })
                else:
                    # 複雜編輯（>=3 次）：完整 reflection
                    task_summary = self._get_current_task_summary()
                    reflection = self._reflect(f"剛剛使用了 {action.tool} 工具，測試結果如下")
                    self.messages.append(
                        {"role": "system", "content": f"=== Reflection ===\n{reflection}"}
                    )
                    self.messages.append({
                        "role": "system",
                        "content": (
                            f"目前任務狀態：\n{task_summary}\n\n"
                            'REMINDER: respond with exactly one JSON object. '
                            '{"type":"final","content":"..."} or {"type":"tool_call","tool":"...","args":{...}}'
                        ),
                    })

        # Fallback: force a final answer before giving up
        self.messages.append({
            "role": "user",
            "content": (
                "你已經用完所有步驟。請立即總結你完成的工作，用以下格式回覆：\n"
                '{"type":"final","content":"你的總結"}'
            ),
        })
        try:
            raw = self.ollama.chat(self.messages, json_mode=True, cancel_event=cancel_event)
            action = self._parse_action(raw)
            if isinstance(action, FinalAnswer):
                return self._handle_final_answer(action.content, effective_plan_only)
        except Exception:
            pass
        self.last_termination = "max_steps_exceeded"
        if self.hooks:
            self.hooks.fire(HookEvent.SESSION_END, SessionEndContext(
                namespace=namespace, termination="max_steps_exceeded",
                message_count=len(self.messages), error_count=len(self.error_history),
            ))
        return "模型沒有輸出有效的工具呼叫 JSON，已停止。請改用 /mode chat 或換更擅長 tool calling 的模型。"

    def clear(self) -> None:
        """完整重置（包含 tasks）。僅供需要完全重置的場合使用。"""
        self.clear_context()
        self.tasks = []
        save_tasks(self.settings.workspace, self.tasks)

    def clear_context(self) -> None:
        """只重置對話上下文與錯誤狀態，不影響 tasks。/clear slash command 應使用此方法。"""
        self.messages = self._initial_messages()
        self.error_history = []
        self.current_error = None
        self._file_ops = {}
        self._tool_outcomes = {}
        self._last_compact_tokens = None
        self._final_guard_retries = 0
        self.last_termination = "unknown"
        self.last_failing_tools = set()
        self.pending_verifies = set()
        # Persist the cleared state
        self._persist_state_event("tool_outcomes", {})
        self._persist_state_event("file_ops", {})
        self._persist_state_event("last_failing_tools", [])
        self._persist_state_event("pending_verifies", [])

    # === Task Management (for complex long-horizon tasks) ===

    def add_task(self, description: str, notes: str = "") -> dict:
        task = {
            "id": get_next_task_id(self.tasks),
            "description": description,
            "status": "pending",
            "notes": notes,
        }
        self.tasks.append(task)
        save_tasks(self.settings.workspace, self.tasks)  # Micro-task 21: 自動持久化
        return task

    def update_task(self, task_id: int | str, status: str | None = None, notes: str | None = None) -> dict | None:
        # 對本地模型更寬容：允許 task_id 是字串或數字
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return None

        # 限制 status 只能是合法值，避免污染持久化資料
        valid_status = {"pending", "in_progress", "done"}
        if status is not None and status not in valid_status:
            return None

        for task in self.tasks:
            if task["id"] == task_id:
                if status:
                    task["status"] = status
                if notes is not None:
                    task["notes"] = notes
                save_tasks(self.settings.workspace, self.tasks)  # Micro-task 21: 自動持久化
                return task
        return None

    def get_tasks(self, status: str | None = None) -> list[dict]:
        if status:
            return [t for t in self.tasks if t["status"] == status]
        return self.tasks

    def clear_tasks(self) -> None:
        self.tasks = []
        save_tasks(self.settings.workspace, self.tasks)  # Micro-task 21: 自動持久化

    def _get_current_task_summary(self) -> str:
        """取得目前任務清單摘要，用於 prompt 注入（B3）"""
        if not self.tasks:
            return "目前沒有任何任務。"
        return format_task_list_summary(self.tasks)

    def _build_retry_guidance(self, tool_name: str, error_message: str, error_type: ErrorType) -> str:
        """為暫時性或呼叫錯誤產生重試引導訊息"""
        if error_type == ErrorType.TRANSIENT:
            return (
                f"【暫時性錯誤】工具 `{tool_name}` 執行失敗：{error_message}\n"
                "這看起來是暫時性問題（例如超時、連線問題）。\n"
                "建議：稍等一下或直接重試同樣參數。如果連續失敗，請考慮改用其他方式或進行 Reflection。"
            )
        elif error_type == ErrorType.CALL_ERROR:
            return (
                f"【呼叫錯誤】工具 `{tool_name}` 執行失敗：{error_message}\n"
                "這通常是因為參數有誤（路徑不存在、參數型別錯誤等）。\n"
                "建議：檢查參數後重新呼叫工具。如果不確定，請先使用 list_files 或 read_file 確認環境。"
            )
        return f"工具 `{tool_name}` 發生錯誤：{error_message}"

    def _build_error_reflection_guidance(self, error_ctx: ErrorContext) -> str:
        """當發生較嚴重錯誤時，產生引導模型進行結構化錯誤 Reflection 的訊息"""
        return (
            f"【錯誤 Reflection 引導】\n"
            f"工具 `{error_ctx.tool_name}` 發生錯誤（類型：{error_ctx.error_type.value}）。\n"
            f"錯誤訊息：{error_ctx.error_message}\n\n"
            "請現在進行一次**結構化的錯誤 Reflection**，回答以下問題：\n"
            "1. 這個錯誤的根本原因是什麼？\n"
            "2. 這屬於哪一類錯誤（暫時性 / 呼叫錯誤 / 執行錯誤 / 需求誤解）？\n"
            "3. 建議的恢復策略是什麼？（重試 / 修正參數 / 回退修改 / 調整任務 / 詢問使用者）\n"
            "4. 是否需要更新 Task List？\n\n"
            "請輸出 reflect，並在 focus 中寫明「錯誤分析與恢復策略」。"
        )

    def _detect_stuck(self, new_error: ErrorContext, threshold: int = 3) -> bool:
        """
        簡單的 STUCK 偵測：
        如果最近 N 次錯誤都是「同一個工具」且「同一類錯誤」，則視為 STUCK。
        """
        if len(self.error_history) < threshold:
            return False

        recent_errors = self.error_history[-threshold:]
        same_tool = all(e.tool_name == new_error.tool_name for e in recent_errors)
        same_type = all(e.error_type == new_error.error_type for e in recent_errors)

        return same_tool and same_type

    def _build_stuck_intervention_message(self, error_ctx: ErrorContext) -> str:
        """
        Phase B2 成熟化版本：
        當偵測到 STUCK 時，給予更結構化、更有行動力的介入訊息。
        """
        suggestions = self._generate_recovery_suggestions(error_ctx)

        suggestion_block = ""
        if suggestions:
            suggestion_block = "\n\n【系統建議的恢復選項（由高到低優先）】\n"
            for i, s in enumerate(suggestions, 1):
                suggestion_block += (
                    f"{i}. **{s.action.value}**（信心 {s.confidence:.0%}）\n"
                    f"   {s.description}\n"
                    f"   理由：{s.rationale}\n\n"
                )

        return (
            f"【⚠️ STUCK 偵測 - 請立即介入】\n"
            f"你已經在工具 `{error_ctx.tool_name}` 上連續遇到相同類型錯誤（{error_ctx.error_type.value}）多次。\n"
            f"這強烈表示目前的策略有根本問題。\n\n"
            "請**立刻停止**重複相同操作，並進行一次認真的 Reflection。\n"
            "在 Reflection 中請明確回答：\n"
            "1. 目前卡住的核心假設是什麼？\n"
            "2. 你接下來要採取哪一個恢復動作？\n"
            f"{suggestion_block}"
            "強烈建議現在輸出 reflect，並在 focus 中寫明你選擇的恢復方向。"
        )

    def _generate_recovery_suggestions(self, error_ctx: ErrorContext) -> list[RecoverySuggestion]:
        """
        Phase B2 成熟化版本：委派給 RecoveryPlaybook。
        產生更有系統性、更有優先序的恢復建議。
        """
        return self.recovery_playbook.generate_suggestions(
            error_ctx,
            self.error_history,
            tasks=self.tasks,
        )  # 最多給 3 個建議，避免提示過長

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def context_chars(self) -> int:
        return sum(len(message.get("content", "")) for message in self.messages)

    @property
    def context_tokens_estimate(self) -> int:
        return self.context_chars // 4

    def context_report(self) -> dict[str, int | str]:
        return {
            "namespace": self.namespace,
            "messages": self.message_count,
            "chars": self.context_chars,
            "tokens_estimate": self.context_tokens_estimate,
            "compactions": self.compaction_count,
        }

    @property
    def last_recovery_suggestions(self) -> list[str]:
        """Phase B2：上次錯誤恢復建議（供 /status 或 transcript 觀測）"""
        if self.recovery_playbook.last_record:
            return self.recovery_playbook.last_record.suggested_actions
        return []

    def _maybe_auto_compact(self) -> None:
        limit = getattr(self.settings, "context_limit_tokens", 8192)
        if not isinstance(limit, (int, float)) or limit <= 0:
            return
        current = self.context_tokens_estimate
        if current <= limit * 0.82:
            return
        if self._last_compact_tokens is not None and current <= self._last_compact_tokens:
            return
        try:
            compact_result = self.compact(keep_last=5)
            self._last_compact_tokens = self.context_tokens_estimate
            self._emit_trace(f"auto_compact triggered: {compact_result}")
        except Exception as e:
            self._emit_trace(f"auto_compact failed (safe): {e}")

    def compact(self, keep_last: int = 6) -> str:
        """
        Context Compaction v2（Phase B1）。

        使用 HeuristicContextCompactor 產生結構化摘要，
        強制保留目前任務清單、重要 Reflection 與決策歷史。
        """
        before_count = len(self.messages)
        self._scan_messages_for_file_ops(self.messages)
        new_messages, result = self.compactor.compact(
            self.messages,
            self.tasks,
            keep_last=keep_last,
            error_history=self.error_history,
        )

        file_summary = self._build_file_ops_summary() if self._file_ops else ""
        if file_summary:
            new_messages.append({"role": "system", "content": file_summary})

        if len(new_messages) >= before_count and not file_summary:
            result = "壓縮跳過（訊息數量不足）"
        else:
            self.messages = new_messages
        self.compaction_count += 1

        self._persist_state_event("compaction_count", self.compaction_count)
        self._persist_state_event("file_ops", {k: list(v) for k, v in self._file_ops.items()})

        if self.hooks:
            self.hooks.fire(HookEvent.COMPACT, CompactContext(
                before_count=before_count, after_count=len(self.messages),
                tokens_estimate=self.context_tokens_estimate, summary=result,
            ))

        return (
            f"壓縮完成：{result} 目前約 {self.context_tokens_estimate} tokens。"
        )

    def _handle_final_answer(self, content: str, plan_only: bool) -> str:
        self.messages.append({"role": "assistant", "content": content})
        self._persist_message("assistant", content)
        self.last_termination = "final"
        self.last_failing_tools = self._unresolved_failing_tools()
        if self.hooks:
            self.hooks.fire(HookEvent.FINAL_ANSWER, FinalAnswerContext(
                content=content, plan_only=plan_only,
                message_count=len(self.messages),
            ))
            # Codex feedback: fire SESSION_END on normal successful final too
            # (currently only fired on max_steps_exceeded in the outer loop).
            self.hooks.fire(HookEvent.SESSION_END, SessionEndContext(
                namespace=self.namespace,
                termination="final",
                message_count=len(self.messages),
                error_count=len(self.error_history),
            ))
        return content

    def _parse_action(self, raw: str) -> ToolCall | FinalAnswer | Reflect | "InvalidAction":
        data = extract_json_object(raw)
        if data is None:
            return InvalidAction.NON_JSON

        try:
            if data.get("type") == "tool_call":
                return ToolCall.model_validate(data)
            if data.get("type") == "reflect":
                return Reflect.model_validate(data)
            return FinalAnswer.model_validate(data)
        except (AttributeError, ValidationError):
            return InvalidAction.BAD_SCHEMA

    def _format_tool_result(self, result: ToolResult) -> str:
        return result.model_dump_json()

    _FILE_WRITE_TOOLS = {"write_file", "edit_file", "search_replace", "insert_code", "apply_patch"}
    _FILE_READ_TOOLS = {"read_file"}

    def _run_tool(self, action: ToolCall) -> ToolResult:
        self._emit_trace(f"tool_call {action.tool} args={action.args}")
        # Use _return_effective so file-op tracking (and future audit) sees the args
        # after any PRE hook rewrite (Codex review feedback on consistency).
        ret = self.tools.run(action.tool, action.args, _return_effective=True)
        if isinstance(ret, tuple):
            result, effective_args = ret
        else:
            result, effective_args = ret, action.args
        summary = result.content.replace("\n", "\\n")[:240]
        self._emit_trace(f"tool_result {action.tool} ok={result.ok} content={summary}")
        self._track_file_op_from_args(action.tool, effective_args)
        if not result.ok:
            self._tool_outcomes[action.tool] = False
        elif result.ok and re.search(r'\bexit=([1-9]\d*)\b', result.content or ""):
            self._tool_outcomes[action.tool] = False
        else:
            self._tool_outcomes[action.tool] = True
        self._persist_state_event("tool_outcomes", dict(self._tool_outcomes))
        self._persist_state_event("last_failing_tools", list(self.last_failing_tools))
        return result

    def _unresolved_failing_tools(self) -> set[str]:
        return {name for name, ok in self._tool_outcomes.items() if not ok}

    def _track_file_op(self, action: ToolCall) -> None:
        # Legacy path (kept for _scan_messages_for_file_ops which reconstructs from history)
        self._track_file_op_from_args(action.tool, action.args)

    def _track_file_op_from_args(self, tool: str, args: dict[str, Any]) -> None:
        """Track read/write using the *effective* args (after PRE hook rewrite if any)."""
        path = args.get("path") if isinstance(args, dict) else None
        if not path:
            return
        path = str(path)
        if path not in self._file_ops:
            self._file_ops[path] = set()
        if tool in self._FILE_WRITE_TOOLS:
            self._file_ops[path].add("write")
        elif tool in self._FILE_READ_TOOLS:
            self._file_ops[path].add("read")
        # Persist snapshot so resume knows what was touched (Codex item)
        self._persist_state_event("file_ops", {k: list(v) for k, v in self._file_ops.items()})

    def _scan_messages_for_file_ops(self, messages: list[dict[str, Any]]) -> None:
        import json as _json
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            try:
                data = _json.loads(content)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict) or data.get("type") != "tool_call":
                continue
            tool = data.get("tool", "")
            path = (data.get("args") or {}).get("path")
            if not path:
                continue
            path = str(path)
            if path not in self._file_ops:
                self._file_ops[path] = set()
            if tool in self._FILE_WRITE_TOOLS:
                self._file_ops[path].add("write")
            elif tool in self._FILE_READ_TOOLS:
                self._file_ops[path].add("read")

    def _build_file_ops_summary(self) -> str:
        modified = []
        read_only = []
        for path, ops in sorted(self._file_ops.items()):
            if "write" in ops:
                modified.append(path)
            elif "read" in ops:
                read_only.append(path)
        parts = []
        if modified:
            parts.append(f"<modified-files>\n{chr(10).join(modified)}\n</modified-files>")
        if read_only:
            parts.append(f"<read-files>\n{chr(10).join(read_only)}\n</read-files>")
        return "\n".join(parts)

    def _handle_task_tool(self, action: ToolCall) -> ToolResult:
        """Internal task management for the agent."""
        tool = action.tool
        args = action.args

        try:
            if tool == "task_add":
                desc = args.get("description", "")
                notes = args.get("notes", "")
                task = self.add_task(desc, notes)
                return ToolResult(tool=tool, ok=True, content=f"Task added: {task}")

            elif tool == "task_update":
                task_id = args.get("task_id")
                status = args.get("status")
                notes = args.get("notes")
                task = self.update_task(task_id, status, notes)
                if task:
                    return ToolResult(tool=tool, ok=True, content=f"Task updated: {task}")
                else:
                    return ToolResult(tool=tool, ok=False, content=f"Task {task_id} not found")

            elif tool == "task_list":
                status = args.get("status")
                tasks = self.get_tasks(status)
                # B2: 回傳結構化、易讀的任務摘要，而不是原始 dict list
                # 讓本地模型更容易理解目前任務狀態
                if tasks:
                    content = format_task_list_summary(tasks)
                else:
                    content = "目前沒有任何任務。"
                if status:
                    content = f"篩選條件: status={status}\n{content}"
                return ToolResult(tool=tool, ok=True, content=content)

            else:
                return ToolResult(tool=tool, ok=False, content=f"Unknown task tool: {tool}")

        except Exception as e:
            return ToolResult(tool=tool, ok=False, content=str(e))

    def _reflect(self, focus: str | None = None) -> str:
        """讓模型對最近的行為進行自我檢討，並明確建議下一步。"""
        focus_text = f"\n特別關注：{focus}" if focus else ""

        reflection_prompt = (
            "你剛剛執行了一些工具呼叫。請誠實地進行自我檢討：\n"
            f"{focus_text}\n\n"
            "請回答以下問題：\n"
            "1. 最近的工具結果是否符合預期？有什麼問題或風險？\n"
            "2. 目前任務的進度如何？\n"
            "3. **下一步最建議做什麼？**（請給出明確的行動建議，例如：繼續修復、執行更多測試、輸出最終方案、需要更多資訊等）\n\n"
            "請用清晰的 bullet points 回覆，並在最後一段清楚寫出「下一步建議」。"
        )

        # 暫時把 reflection_prompt 當成 user message 丟給模型
        reflection_messages = self.messages + [
            {"role": "user", "content": reflection_prompt}
        ]

        try:
            reflection = self.ollama.chat(
                reflection_messages, json_mode=False, cancel_event=None
            )
            return reflection.strip()
        except Exception as e:
            return f"Reflection 失敗: {str(e)}"

    def _emit_trace(self, message: str) -> None:
        if self.trace is not None:
            self.trace(message)

    def _direct_tool_call(self, prompt: str) -> ToolCall | None:
        normalized = prompt.lower()
        if len(normalized) > 200:
            return None
        write_keywords = ("write_file", "建立", "實作", "寫", "create", "implement")
        if any(kw in normalized for kw in write_keywords):
            return None
        if any(keyword in normalized for keyword in ("列出", "list files")):
            if any(keyword in normalized for keyword in ("repo", "目錄", "directory", "workspace")):
                return ToolCall(type="tool_call", tool="list_files", args={"path": "."})
        if normalized.strip() == "git status":
            return ToolCall(type="tool_call", tool="git_status", args={})
        return None


class InvalidAction(Enum):
    NON_JSON = "non_json"
    BAD_SCHEMA = "bad_schema"
