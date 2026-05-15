from __future__ import annotations

import json as _json
import re as _re
import threading
from collections.abc import Callable
from enum import Enum

from pydantic import ValidationError

from agentx.bootstrap import build_memory_context, build_repo_context
from agentx.config import Settings
from agentx.hooks import HookManager
from agentx.json_repair import extract_json_object
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.protocol import FinalAnswer, ToolCall, ToolResult
from agentx.runtime_prompt import build_agent_system_prompt
from agentx.tools import ToolRegistry


class InvalidAction(Enum):
    NON_JSON = "non_json"
    BAD_SCHEMA = "bad_schema"


class AgentLoop:
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
        self.session = AgentSession(
            settings=settings,
            ollama=ollama,
            tools=tools,
            memory=memory,
            namespace=namespace,
            trace=trace,
            hooks=hooks,
        )

    def run(
        self,
        prompt: str,
        namespace: str = "project:agentX",
        cancel_event: threading.Event | None = None,
    ) -> str:
        return self.session.ask(prompt, namespace=namespace, cancel_event=cancel_event)


class AgentSession:
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
        if hooks is not None:
            self.tools.hooks = hooks
        self.compaction_count = 0
        # Outcome of the most recent ask() — coordinator / callers consume these
        # for structured success judgment (review N5: don't rely on string
        # prefixes of the summary).
        self.last_termination: str = "unknown"
        self.last_failing_tools: set[str] = set()
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
        self.messages = self._initial_messages()

    def _initial_messages(self) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": build_agent_system_prompt(self.settings.persona, tools=self.tools),
            },
            {"role": "system", "content": "Repo bootstrap context:\n" + build_repo_context(self.settings.workspace)},
            {
                "role": "system",
                "content": "Memory Hall context:\n"
                + build_memory_context(
                    self.memory,
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
    ) -> str:
        self.last_termination = "running"
        self.last_failing_tools = set()
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

        finalize_retries = 0
        for _ in range(self.settings.max_steps):
            self._maybe_auto_compact()
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
                if failing and finalize_retries < self.MAX_FINALIZE_RETRIES:
                    finalize_retries += 1
                    self.messages.append({"role": "assistant", "content": action.content})
                    failing_summary = ", ".join(sorted(failing))
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"上一次 {failing_summary} 工具回應顯示失敗（exit≠0 或 ok=false）。"
                                "在問題解決前不可以下成功結論。請繼續呼叫工具修正，"
                                "或若確定卡住，請用 type=final 明確說明失敗原因，不要含糊。"
                            ),
                        }
                    )
                    continue
                if failing:
                    # Retries exhausted with unresolved failures — refuse to
                    # propagate the model's final claim (review N7). Replace
                    # with a forced failure summary that callers / coordinators
                    # can rely on for honest reporting.
                    failing_summary = ", ".join(sorted(failing))
                    forced_final = (
                        f"任務失敗：經過 {self.MAX_FINALIZE_RETRIES + 1} 次嘗試後，"
                        f"以下工具仍處於失敗狀態：{failing_summary}。"
                        f"模型最後一次回應（僅供參考、非結論）："
                        f"{action.content.replace(chr(10), ' ')[:400]}"
                    )
                    self.messages.append({"role": "assistant", "content": forced_final})
                    self.last_failing_tools = failing
                    self.last_termination = "final"
                    return forced_final
                self.messages.append({"role": "assistant", "content": action.content})
                self.last_failing_tools = set()
                self.last_termination = "final"
                return action.content

            result = self._run_tool(action)
            self.messages.append({"role": "assistant", "content": action.model_dump_json()})
            self.messages.append({"role": "tool", "content": self._format_tool_result(result)})

        self.last_failing_tools = self._unresolved_failing_tools()
        self.last_termination = "max_steps_exceeded"
        return "模型沒有輸出有效的工具呼叫 JSON，已停止。請改用 /mode chat 或換更擅長 tool calling 的模型。"

    MAX_FINALIZE_RETRIES = 3
    AUTO_COMPACT_RATIO = 0.7
    # Don't re-compact unless context has grown by at least this fraction of
    # the limit since the previous compact (hysteresis, review N8).
    AUTO_COMPACT_HYSTERESIS_RATIO = 0.1
    _EXIT_FAIL_RE = _re.compile(r"\bexit=([1-9]\d*)\b")

    def _maybe_auto_compact(self) -> None:
        limit = self.settings.context_limit_tokens
        if limit <= 0:
            return
        current = self.context_tokens_estimate
        if current < limit * self.AUTO_COMPACT_RATIO:
            return
        if self._last_compact_tokens is not None:
            growth = current - self._last_compact_tokens
            if growth < limit * self.AUTO_COMPACT_HYSTERESIS_RATIO:
                # Already compacted recently; bootstrap + summary alone are
                # above threshold. Compacting again would burn cycles and
                # rebuild the same summary without freeing meaningful space.
                self._emit_trace(
                    f"auto-compact skipped: only +{growth} tokens since last compact"
                )
                return
        try:
            self._emit_trace(f"auto-compact at {current} tokens (limit={limit})")
            self.compact()
            self._last_compact_tokens = self.context_tokens_estimate
        except Exception as exc:  # don't crash the agent loop on compact failure
            self._emit_trace(f"auto-compact failed: {type(exc).__name__}: {exc}")

    def _unresolved_failing_tools(self) -> set[str]:
        return {name for name, ok in self._tool_outcomes.items() if not ok}

    def clear(self) -> None:
        self.messages = self._initial_messages()
        # Reset session bookkeeping so a fresh task starts clean (review codex
        # C2: stale _last_compact_tokens disables auto-compact across /clear).
        self._last_compact_tokens = None
        self._tool_outcomes = {}
        self.last_termination = "unknown"
        self.last_failing_tools = set()

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

        read_files, modified_files = self._extract_file_operations()
        if read_files:
            summary_lines.append("")
            summary_lines.append("<read-files>")
            for path in sorted(read_files):
                summary_lines.append(f"  {path}")
            summary_lines.append("</read-files>")
        if modified_files:
            summary_lines.append("")
            summary_lines.append("<modified-files>")
            for path in sorted(modified_files):
                summary_lines.append(f"  {path}")
            summary_lines.append("</modified-files>")

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

    _FILE_READ_TOOLS = frozenset({"read_file"})
    _FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})

    def _extract_file_operations(self) -> tuple[set[str], set[str]]:
        read_files: set[str] = set()
        modified_files: set[str] = set()
        for msg in self.messages:
            if msg.get("role") != "assistant":
                continue
            try:
                data = _json.loads(msg.get("content", "") or "{}")
            except _json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("type") != "tool_call":
                continue
            tool = str(data.get("tool", ""))
            args = data.get("args") or {}
            if not isinstance(args, dict):
                continue
            path = args.get("path")
            if not isinstance(path, str) or not path:
                continue
            if tool in self._FILE_READ_TOOLS:
                read_files.add(path)
            elif tool in self._FILE_WRITE_TOOLS:
                modified_files.add(path)
        read_files -= modified_files
        return read_files, modified_files

    def _parse_action(self, raw: str) -> ToolCall | FinalAnswer | InvalidAction:
        data = extract_json_object(raw)
        if data is None:
            return InvalidAction.NON_JSON
        try:
            if data.get("type") == "tool_call":
                return ToolCall.model_validate(data)
            return FinalAnswer.model_validate(data)
        except ValidationError:
            return InvalidAction.BAD_SCHEMA

    def _format_tool_result(self, result: ToolResult) -> str:
        return result.model_dump_json()

    def _run_tool(self, action: ToolCall) -> ToolResult:
        self._emit_trace(f"tool_call {action.tool} args={action.args}")
        result = self.tools.run(action.tool, action.args)
        # Persist per-tool outcome so unresolved failures don't fall off a
        # window when other tools are called later (review codex C3). Treat
        # exit=N (N≠0) inside content as failure even when ok=True (registry
        # wraps subprocess exit codes that way).
        is_failure = (not result.ok) or bool(self._EXIT_FAIL_RE.search(result.content))
        self._tool_outcomes[result.tool] = not is_failure
        summary = result.content.replace("\n", "\\n")[:240]
        self._emit_trace(f"tool_result {action.tool} ok={result.ok} content={summary}")
        return result

    def _emit_trace(self, message: str) -> None:
        if self.trace is not None:
            self.trace(message)
