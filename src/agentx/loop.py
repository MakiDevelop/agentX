from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum

from pydantic import ValidationError

from agentx.bootstrap import build_memory_context, build_repo_context
from agentx.config import Settings
from agentx.json_repair import extract_json_object
from agentx.ollama import OllamaClient
from agentx.protocol import FinalAnswer, Reflect, ToolCall, ToolResult
from agentx.runtime_prompt import build_agent_system_prompt
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
    ) -> None:
        self.session = AgentSession(
            settings=settings,
            ollama=ollama,
            tools=tools,
            namespace=namespace,
            trace=trace,
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
    ) -> None:
        self.settings = settings
        self.ollama = ollama
        self.tools = tools
        self.namespace = namespace
        self.trace = trace
        self.compaction_count = 0
        self.plan_only: bool = False
        self.messages = self._initial_messages()

    def _initial_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": build_agent_system_prompt(self.settings.persona)},
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
                reflection = self._reflect(action.focus)
                self.messages.append({"role": "assistant", "content": action.model_dump_json()})
                self.messages.append(
                    {"role": "system", "content": f"=== Reflection ===\n{reflection}"}
                )
                continue

            if effective_plan_only:
                # Real enforcement: do not execute tools in plan mode.
                # Force the model to produce a final answer describing the plan.
                self.messages.append({"role": "assistant", "content": action.model_dump_json()})
                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你目前處於 PLAN MODE，工具呼叫已被停用。\n"
                            "請不要再輸出 tool_call JSON。\n"
                            "請改用結構化方式描述方案：\n"
                            "1. 目標\n"
                            "2. 執行步驟（編號）\n"
                            "3. 每個步驟會用到的工具\n"
                            "4. 風險與依賴\n"
                            "5. 驗證方式\n\n"
                            "最後請輸出 final answer。"
                        ),
                    }
                )
                continue

            result = self._run_tool(action)
            self.messages.append({"role": "assistant", "content": action.model_dump_json()})
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})

            # Micro-task 12：編輯工具成功後，自動執行測試 + Reflection
            if action.tool in EDITING_TOOLS and result.ok:
                # 自動跑測試
                test_result = self.tools.run("run_tests", {})
                self.messages.append({"role": "tool", "content": self._format_tool_result(test_result)})

                # 再自動 Reflection（此時 Reflection 會看到測試結果）
                reflection = self._reflect(f"剛剛使用了 {action.tool} 工具，測試結果如下")
                self.messages.append(
                    {"role": "system", "content": f"=== 自動 Reflection（編輯 + 測試後） ===\n{reflection}"}
                )

                # Micro-task 13：Reflection 後強迫模型主動決定下一步
                self.messages.append(
                    {
                        "role": "system",
                        "content": (
                            "根據剛剛的 Reflection，請現在明確輸出你建議的下一步行動。\n"
                            "你可以：\n"
                            "- 呼叫工具繼續執行\n"
                            "- 輸出 final answer\n"
                            "- 再次 reflect 更深入的問題\n\n"
                            "請直接給出清晰的下一步，不要猶豫。"
                        ),
                    }
                )

        return "模型沒有輸出有效的工具呼叫 JSON，已停止。請改用 /mode chat 或換更擅長 tool calling 的模型。"

    def clear(self) -> None:
        self.messages = self._initial_messages()

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
