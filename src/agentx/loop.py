from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum

from pydantic import ValidationError

from agentx.bootstrap import build_memory_context, build_repo_context
from agentx.config import Settings
from agentx.json_repair import extract_json_object
from agentx.ollama import OllamaClient
from agentx.errors import ErrorContext, ErrorType, RecoveryAction, RecoverySuggestion
from agentx.error_classifier import ErrorClassifier
from agentx.protocol import FinalAnswer, Reflect, ToolCall, ToolResult
from agentx.runtime_prompt import build_agent_system_prompt
from agentx.tasks import format_task_list_summary, get_next_task_id, load_tasks, save_tasks
from agentx.tools import ToolRegistry

EDITING_TOOLS = {"search_replace", "insert_code", "apply_patch"}


class AgentLoop:
    def __init__(
        self,
        settings: Settings,
        ollama: OllamaClient,
        tools: ToolRegistry,
        namespace: str = "project:agentX",
        trace: Callable[[str], None] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.session = AgentSession(
            settings=settings,
            ollama=ollama,
            tools=tools,
            namespace=namespace,
            trace=trace,
            system_prompt=system_prompt,
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
        # Reflection loop guard for headless stability (Micro-task 20)
        self.consecutive_reflections: int = 0
        self.max_consecutive_reflections: int = 3

        # Task List 持久化載入（Micro-task 21 A2）
        self.tasks: list[dict] = load_tasks(self.settings.workspace)

        # 錯誤恢復相關狀態（階段一）
        self.error_classifier = ErrorClassifier()
        self.error_history: list[ErrorContext] = []
        self.current_error: ErrorContext | None = None

        self.messages = self._initial_messages()

    def _initial_messages(self) -> list[dict[str, str]]:
        system_prompt = self._custom_system_prompt or build_agent_system_prompt(self.settings.persona)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": "Repo bootstrap context:\n" + build_repo_context(self.settings.workspace)},
            {
                "role": "system",
                "content": "Memory Hall context:\n"
                + build_memory_context(
                    self.tools.memory,
                    project_namespace=self.namespace,
                    query=f"{self.settings.workspace.name} project context",
                ),
            },
        ]

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
            if result.ok:
                return result.content
            return f"工具執行失敗：{result.content}"

        self.messages.append(
            {
                "role": "user",
                "content": (
                    f"Workspace: {self.settings.workspace}\n"
                    f"Default memory namespace: {namespace}\n"
                    f"Task: {prompt}"
                ),
            }
        )

        for _ in range(self.settings.max_steps):
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
                self.messages.append({"role": "assistant", "content": action.content})
                return action.content

            if isinstance(action, Reflect):
                self.consecutive_reflections += 1
                reflection = self._reflect(action.focus)
                self.messages.append({"role": "assistant", "content": action.model_dump_json()})
                self.messages.append(
                    {"role": "system", "content": f"=== Reflection ===\n{reflection}"}
                )
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
                            "強制進度，停止純粹 Reflection。guard 已重置。"
                        )
                    self.messages.append({"role": "system", "content": guard_msg})
                    self.consecutive_reflections = 0  # give one more chance after warning
                continue

            if effective_plan_only and not self._has_completed_planning:
                # In headless plan mode, we require at least one reflection before allowing tool execution.
                # This ensures the model has seriously thought through the plan.
                self.messages.append({"role": "assistant", "content": action.model_dump_json()})
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

            self.messages.append({"role": "assistant", "content": action.model_dump_json()})
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})

            # === 錯誤分類與基礎恢復處理（階段一 + 步驟 4） ===
            if not result.ok:
                error_type = self.error_classifier.classify(action.tool, result)
                self.current_error = ErrorContext(
                    error_type=error_type,
                    tool_name=action.tool,
                    error_message=result.content or "",
                )
                self.error_history.append(self.current_error)

                # === STUCK 偵測（階段二步驟 1） ===
                if self._detect_stuck(self.current_error):
                    self.current_error.error_type = ErrorType.STUCK
                    stuck_msg = self._build_stuck_intervention_message(self.current_error)
                    self.messages.append({"role": "system", "content": stuck_msg})
                    # STUCK 時強烈建議進行 Reflection
                    self.messages.append({
                        "role": "system",
                        "content": "請立即輸出 reflect，專注解決當前卡住的問題。"
                    })
                    continue  # 跳過後續執行，讓模型在下一輪有機會回應 STUCK 訊息

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

            # Micro-task 12：編輯工具成功後，自動執行測試 + Reflection
            if action.tool in EDITING_TOOLS and result.ok:
                # 自動跑測試
                test_result = self.tools.run("run_tests", {})
                self.messages.append({"role": "tool", "content": self._format_tool_result(test_result)})

                # 編輯後提醒模型更新 Task List（實際流程中模型會在下一輪有機會先呼叫 task_update）
                task_summary = self._get_current_task_summary()
                self.messages.append(
                    {
                        "role": "system",
                        "content": (
                            "如果你剛剛有修改任務，請記得在接下來的回應中先使用 task_update 工具更新 Task List 的狀態。\n"
                            "之後再進行 Reflection，並給出明確的下一步建議。\n\n"
                            f"目前任務狀態參考：\n{task_summary}"
                        ),
                    }
                )

                # 再自動 Reflection
                reflection = self._reflect(f"剛剛使用了 {action.tool} 工具，測試結果如下")
                self.messages.append(
                    {"role": "system", "content": f"=== 自動 Reflection（編輯 + 測試後） ===\n{reflection}"}
                )

                # Micro-task 14：Reflection 後主動建議 Review + Commit（當適當時機）
                task_summary = self._get_current_task_summary()
                self.messages.append(
                    {
                        "role": "system",
                        "content": (
                            "根據剛剛的 Reflection，請評估目前變更是否已經穩定（測試通過、風險可控）。\n"
                            "如果變更已經足夠好，請主動建議使用者執行以下流程：\n"
                            "1. 使用 /review 進行程式碼審查\n"
                            "2. 使用 /commit 進行逐檔 stage + 中文 commit + push\n\n"
                            "如果還不適合 commit，請清楚說明還需要做什麼。\n"
                            "請給出明確的下一步建議。\n\n"
                            f"目前任務狀態參考：\n{task_summary}"
                        ),
                    }
                )

        return "模型沒有輸出有效的工具呼叫 JSON，已停止。請改用 /mode chat 或換更擅長 tool calling 的模型。"

    def clear(self) -> None:
        self.messages = self._initial_messages()
        self.tasks = []
        save_tasks(self.settings.workspace, self.tasks)  # Micro-task 21: 自動持久化

        # 重置錯誤狀態
        self.error_history = []
        self.current_error = None

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
        """當偵測到 STUCK 時，給予強烈介入訊息，並附上恢復建議"""
        suggestions = self._generate_recovery_suggestions(error_ctx)

        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n\n系統建議的恢復方向：\n"
            for i, s in enumerate(suggestions, 1):
                suggestion_text += f"{i}. [{s.action.value}] {s.description}\n"

        return (
            f"【⚠️ STUCK 偵測】\n"
            f"你已經連續多次在工具 `{error_ctx.tool_name}` 上遇到相同類型的錯誤（{error_ctx.error_type.value}）。\n"
            f"這表示目前的做法很可能有問題。\n\n"
            "請立即停止重複相同行為，並進行深度 Reflection：\n"
            "- 為什麼一直失敗？\n"
            "- 是否需要大幅改變策略？\n"
            "- 是否應該回退之前的修改？\n"
            "- 是否需要請求人類協助？"
            f"{suggestion_text}\n"
            "建議現在輸出 reflect，並認真思考恢復方案。"
        )

    def _generate_recovery_suggestions(self, error_ctx: ErrorContext) -> list[RecoverySuggestion]:
        """根據錯誤上下文產生恢復建議（階段二初始版本）"""
        suggestions: list[RecoverySuggestion] = []
        recent_errors = self.error_history[-5:] if self.error_history else []

        # 情況 1: 同一個工具連續失敗多次 → 建議回退
        same_tool_failures = sum(1 for e in recent_errors if e.tool_name == error_ctx.tool_name)
        if same_tool_failures >= 3:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.BACKTRACK,
                description=f"建議回退最近對 `{error_ctx.tool_name}` 的修改，檢查是否有破壞性變更。",
                rationale="同一個工具連續失敗多次，通常表示最後幾次修改有問題。",
                confidence=0.8
            ))

        # 情況 2: EXECUTION_ERROR + 多次失敗 → 建議改變策略
        if error_ctx.error_type == ErrorType.EXECUTION_ERROR and same_tool_failures >= 2:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.CHANGE_STRATEGY,
                description="目前直接修改程式碼的方式似乎不順利，建議先寫測試或先做更小的步驟再修改。",
                rationale="執行錯誤連續發生時，直接修改容易陷入試錯迴圈。",
                confidence=0.7
            ))

        # 情況 3: 錯誤次數很多 → 建議人類介入
        if len(self.error_history) >= 6:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.ESCALATE_TO_USER,
                description="系統已多次嘗試恢復但未成功，建議將目前任務狀態、錯誤歷史摘要整理後請求人類協助。",
                rationale="長時間卡住且多次恢復失敗時，人類介入通常是最有效的方式。",
                confidence=0.9
            ))

        # 預設建議（如果上面都沒觸發）
        if not suggestions:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.REFLECT_AND_ADJUST,
                description="請進行深度 Reflection，分析為什麼會持續失敗，並提出明確的下一步策略。",
                rationale="一般情況下的保守建議。",
                confidence=0.5
            ))

        return suggestions[:3]  # 最多給 3 個建議，避免提示過長

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

    def compact(self, keep_last: int = 8) -> str:
        bootstrap = self._initial_messages()
        tail = self.messages[-keep_last:] if len(self.messages) > keep_last else self.messages
        user_items = [m.get("content", "") for m in self.messages if m.get("role") == "user"]
        tool_items = [m.get("content", "") for m in self.messages if m.get("role") == "tool"]
        assistant_items = [m.get("content", "") for m in self.messages if m.get("role") == "assistant"]

        summary_lines = [
            "Session compacted. Continue from this structured summary.",
            f"- Previous message count: {len(self.messages)}",
            f"- Kept last messages: {len(tail)}",
            "",
            "Current goal / user requests:",
        ]
        for item in user_items[-5:]:
            summary_lines.append(f"- {item.replace(chr(10), ' ')[:500]}")

        summary_lines.extend(["", "Recent assistant conclusions:"])
        for item in assistant_items[-5:]:
            summary_lines.append(f"- {item.replace(chr(10), ' ')[:500]}")

        summary_lines.extend(["", "Recent tool results:"])
        for item in tool_items[-5:]:
            summary_lines.append(f"- {item.replace(chr(10), ' ')[:500]}")

        summary_lines.extend(["", "Recent raw messages:"])
        for message in tail:
            role = message.get("role", "unknown")
            content = message.get("content", "").replace("\n", " ")[:300]
            summary_lines.append(f"- {role}: {content}")
        self.compaction_count += 1
        self.messages = [
            *bootstrap,
            {"role": "system", "content": "\n".join(summary_lines)},
        ]
        return (
            f"已壓縮上下文：保留最近 {len(tail)} 則訊息摘要，"
            f"目前約 {self.context_tokens_estimate} tokens。"
        )

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

    def _run_tool(self, action: ToolCall) -> ToolResult:
        self._emit_trace(f"tool_call {action.tool} args={action.args}")
        result = self.tools.run(action.tool, action.args)
        summary = result.content.replace("\n", "\\n")[:240]
        self._emit_trace(f"tool_result {action.tool} ok={result.ok} content={summary}")
        return result

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
        if any(keyword in normalized for keyword in ("列出", "檔案", "files", "list files")):
            if any(keyword in normalized for keyword in ("repo", "目錄", "directory", "workspace")):
                return ToolCall(type="tool_call", tool="list_files", args={"path": "."})
        if "git status" in normalized:
            return ToolCall(type="tool_call", tool="git_status", args={})
        return None


class InvalidAction(Enum):
    NON_JSON = "non_json"
    BAD_SCHEMA = "bad_schema"
