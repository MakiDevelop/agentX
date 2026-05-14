from __future__ import annotations

import json

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
        self.settings = settings
        self.ollama = ollama
        self.tools = tools

    def run(self, prompt: str, namespace: str = "project:agentX") -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Workspace: {self.settings.workspace}\n"
                    f"Default memory namespace: {namespace}\n"
                    f"Task: {prompt}"
                ),
            },
        ]

        for _ in range(self.settings.max_steps):
            raw = self.ollama.chat(messages)
            action = self._parse_action(raw)
            if isinstance(action, FinalAnswer):
                return action.content

            result = self.tools.run(action.tool, action.args)
            messages.append({"role": "assistant", "content": action.model_dump_json()})
            messages.append({"role": "tool", "content": self._format_tool_result(result)})

        return "已達最大步數，先停止。請縮小任務或提高 AGENTX_MAX_STEPS。"

    def _parse_action(self, raw: str) -> ToolCall | FinalAnswer:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return FinalAnswer(type="final", content=raw)

        try:
            if data.get("type") == "tool_call":
                return ToolCall.model_validate(data)
            return FinalAnswer.model_validate(data)
        except (AttributeError, ValidationError):
            return FinalAnswer(type="final", content=raw)

    def _format_tool_result(self, result: ToolResult) -> str:
        return result.model_dump_json()

