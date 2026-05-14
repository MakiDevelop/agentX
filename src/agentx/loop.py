from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from pydantic import ValidationError

from agentx.bootstrap import build_memory_context, build_repo_context
from agentx.config import Settings
from agentx.json_repair import extract_json_object
from agentx.ollama import OllamaClient
from agentx.protocol import FinalAnswer, ToolCall, ToolResult
from agentx.tools import ToolRegistry


SYSTEM_PROMPT = """You are agentX, a local engineering agent.
You can use tools through strict JSON only.

Return exactly one JSON object per turn:
{"type":"tool_call","tool":"tool_name","args":{...}}
or
{"type":"final","content":"your final answer"}

Available tools:
- list_files(path=".", limit=200)
- read_file(path, max_chars=20000)
- search_text(pattern, path=".", limit=100)
- git_status()
- git_diff(path=null, max_chars=30000)
- memory_search(query, namespace="shared", limit=5)
- memory_write(content, namespace="agent:agentx")
- run_tests()
- apply_patch(patch)

Do not claim you used a tool unless the tool result is present in the conversation.
Prefer read-only inspection first. Use Traditional Chinese for user-facing answers.
"""


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

    def run(self, prompt: str, namespace: str = "project:agentX") -> str:
        return self.session.ask(prompt, namespace=namespace)


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
        self.messages = self._initial_messages()

    def _initial_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
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

    def ask(self, prompt: str, namespace: str = "project:agentX") -> str:
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
            raw = self.ollama.chat(self.messages, json_mode=True)
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

            result = self._run_tool(action)
            self.messages.append({"role": "assistant", "content": action.model_dump_json()})
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})

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

    def _parse_action(self, raw: str) -> ToolCall | FinalAnswer | "InvalidAction":
        data = extract_json_object(raw)
        if data is None:
            return InvalidAction.NON_JSON

        try:
            if data.get("type") == "tool_call":
                return ToolCall.model_validate(data)
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
