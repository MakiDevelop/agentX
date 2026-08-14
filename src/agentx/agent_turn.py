"""One model turn: native tools first, JSON-in-text as fallback.

Kept out of loop.py so the agent loop file stays under the module-size ratchet.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from agentx.chat_turn import ChatTurn
from agentx.errors import ErrorContext, ErrorType
from agentx.hooks import HookEvent, TurnEndContext
from agentx.protocol import FinalAnswer, ToolCall
from agentx.tool_schemas import ollama_tools_from_registry

MUTATION_INTENT = re.compile(
    r"(幫我寫|寫一支|寫一個|寫一份|建立(?:一個)?檔|新增檔|實作|"
    r"create (?:a |the )?(?:file|script|crawler|module)|"
    r"implement |write (?:a |the )?(?:file|script|crawler))",
    re.IGNORECASE,
)


def invoke_model(session: Any, cancel_event: threading.Event | None) -> ChatTurn:
    chat_turn = getattr(session.ollama, "chat_turn", None)
    if callable(chat_turn):
        return chat_turn(
            session.messages,
            tools=ollama_tools_from_registry(session.tools),
            cancel_event=cancel_event,
        )
    raw = session.ollama.chat(session.messages, json_mode=True, cancel_event=cancel_event)
    return ChatTurn(content=raw)


def actions_from_turn(session: Any, turn: ChatTurn) -> list[Any]:
    from agentx.loop import InvalidAction

    if turn.tool_calls:
        return [
            ToolCall(type="tool_call", tool=call.name, args=call.arguments)
            for call in turn.tool_calls
        ]
    action = session._parse_action(turn.content)
    if (
        isinstance(action, InvalidAction)
        and turn.content.strip()
        and session.tool_call_count > 0
    ):
        return [FinalAnswer(type="final", content=turn.content.strip())]
    return [action]


def incomplete_final_reason(session: Any) -> str | None:
    prompt = getattr(session, "_current_user_prompt", "") or ""
    if not MUTATION_INTENT.search(prompt):
        return None
    wrote = any("write" in ops for ops in session._file_ops.values())
    if not wrote:
        return (
            "這個任務需要建立或修改檔案，但目前還沒有成功的 write/edit。"
            "請先用工具完成工作，不要提前宣告完成。"
        )
    return None


def record_native_assistant(session: Any, turn: ChatTurn) -> None:
    session.messages.append(
        {
            "role": "assistant",
            "content": turn.content or "",
            "tool_calls": [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in turn.tool_calls
            ],
        }
    )
    preview = turn.content or ",".join(call.name for call in turn.tool_calls)
    session._persist_message("assistant", preview)


def execute_native_tool(session: Any, action: ToolCall, step: int) -> bool:
    """Run one native tool call. Returns True if the turn should stop (stuck)."""
    from agentx.loop import EDITING_TOOLS

    session.tool_call_count += 1
    if action.tool.startswith("task_"):
        result = session._handle_task_tool(action)
    else:
        result = session._run_tool(action)
    tool_content = session._format_tool_result(result)
    session.messages.append(
        {"role": "tool", "content": tool_content, "tool_name": action.tool}
    )
    session._persist_message("tool", tool_content)
    if session.hooks:
        session.hooks.fire(
            HookEvent.TURN_END,
            TurnEndContext(
                step=step,
                action_type="tool_call",
                tool_name=action.tool,
                result_ok=result.ok,
            ),
        )
    if not result.ok:
        if result.error_type:
            try:
                error_type = ErrorType(result.error_type)
            except ValueError:
                error_type = session.error_classifier.classify(action.tool, result)
        else:
            error_type = session.error_classifier.classify(action.tool, result)
        session.current_error = ErrorContext(
            error_type=error_type,
            tool_name=action.tool,
            error_message=result.content or "",
        )
        session.error_history.append(session.current_error)
        is_stuck = session._detect_stuck(session.current_error)
        if is_stuck:
            session.current_error.error_type = ErrorType.STUCK
            session.messages.append(
                {
                    "role": "system",
                    "content": session._build_stuck_intervention_message(session.current_error),
                }
            )
            return True
        if error_type in (ErrorType.TRANSIENT, ErrorType.CALL_ERROR):
            session.messages.append(
                {
                    "role": "system",
                    "content": session._build_retry_guidance(
                        action.tool, result.content, error_type
                    ),
                }
            )
        else:
            session.messages.append(
                {
                    "role": "system",
                    "content": session._build_error_reflection_guidance(session.current_error),
                }
            )
        return False
    session.current_error = None
    session.consecutive_reflections = 0
    if action.tool in EDITING_TOOLS:
        session._edit_count = getattr(session, "_edit_count", 0) + 1
        session._run_targeted_verifications()
    return False
