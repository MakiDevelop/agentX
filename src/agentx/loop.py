from __future__ import annotations

import json
from enum import Enum

from pydantic import ValidationError

from agentx.config import Settings
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

Do not claim you used a tool unless the tool result is present in the conversation.
Prefer read-only inspection first. Use Traditional Chinese for user-facing answers.
"""


class AgentLoop:
    def __init__(self, settings: Settings, ollama: OllamaClient, tools: ToolRegistry) -> None:
        self.session = AgentSession(settings=settings, ollama=ollama, tools=tools)

    def run(self, prompt: str, namespace: str = "project:agentX") -> str:
        return self.session.ask(prompt, namespace=namespace)


class AgentSession:
    def __init__(self, settings: Settings, ollama: OllamaClient, tools: ToolRegistry) -> None:
        self.settings = settings
        self.ollama = ollama
        self.tools = tools
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

    def ask(self, prompt: str, namespace: str = "project:agentX") -> str:
        direct = self._direct_tool_call(prompt)
        if direct is not None:
            result = self.tools.run(direct.tool, direct.args)
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

            result = self.tools.run(action.tool, action.args)
            self.messages.append({"role": "assistant", "content": action.model_dump_json()})
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})

        return "模型沒有輸出有效的工具呼叫 JSON，已停止。請改用 /mode chat 或換更擅長 tool calling 的模型。"

    def clear(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def _parse_action(self, raw: str) -> ToolCall | FinalAnswer | "InvalidAction":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return InvalidAction.NON_JSON

        try:
            if data.get("type") == "tool_call":
                return ToolCall.model_validate(data)
            return FinalAnswer.model_validate(data)
        except (AttributeError, ValidationError):
            return InvalidAction.BAD_SCHEMA

    def _format_tool_result(self, result: ToolResult) -> str:
        return result.model_dump_json()

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
