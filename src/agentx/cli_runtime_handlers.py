"""Importable runtime slash handlers used by ``run_shell()``.

These implement the real interactive-shell logic for a small set of
commands (``/plan``, ``/execute``, ``/mode``). Nested handlers inside
``cli.run_shell()`` should delegate here so unit tests can exercise the
same path without driving the full interactive loop.

Do not confuse with ``cli_slash_shims`` — those are simplified test-only
dispatch stubs and are *not* the runtime shell path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, MutableSequence

# Exact system message injected when leaving plan mode via /execute.
# Keep in sync with historical run_shell() text (behavior-preserving extract).
EXECUTE_SYSTEM_MESSAGE = (
    "規劃階段已結束，使用者已同意上述方案。\n"
    "你現在已切換至執行模式。請使用工具實際執行方案中的每個步驟。\n"
    "如果需要，可以先列出下一步要做的動作，再逐步呼叫工具完成。"
)


def handle_plan(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    emit: Callable[[str], None],
    format_status: Callable[[bool], str],
) -> None:
    """Toggle plan mode, write transcript, and emit status.

    Dependencies are passed explicitly so tests can stub I/O without
    constructing a full shell console.
    """
    new_plan = not state.plan_mode
    state.set_plan_mode(new_plan)
    transcript.write("slash_command", {"command": prompt, "plan": new_plan})
    status = format_status(state.plan_mode)
    emit(f"plan mode: {status}")


def handle_execute(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    chat_messages: MutableSequence[dict[str, str]],
    emit: Callable[[str], None],
) -> None:
    """Exit plan mode, switch chat→agent if needed, inject execute system message."""
    if not state.plan_mode and not (state.agent_session and state.agent_session.plan_only):
        emit("目前不在 plan 模式中")
        return

    state.set_plan_mode(False)

    # 從 plan 模式執行時，預設切到 agent 模式
    if state.mode == "chat":
        state.set_chat_mode("agent")

    transcript.write(
        "slash_command",
        {"command": prompt, "plan": False, "mode": state.mode, "action": "execute"},
    )

    execute_message = EXECUTE_SYSTEM_MESSAGE
    if state.agent_session:
        state.agent_session.messages.append({"role": "system", "content": execute_message})
    chat_messages.append({"role": "system", "content": execute_message})

    emit(f"已切換至執行模式（mode={state.mode}）。後續提示將可使用工具實際執行方案。")


def handle_mode(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    emit: Callable[[str], None],
    emit_error: Callable[[str], None],
) -> None:
    """Switch chat/agent mode; emit_error on invalid value (matches print_raw path)."""
    next_mode = prompt.removeprefix("/mode ").strip()
    try:
        state.set_chat_mode(next_mode)
    except ValueError:
        emit_error("mode must be chat, ask, or agent")
        return
    transcript.write("slash_command", {"command": prompt, "mode": state.mode})
    emit(f"mode={state.mode}")
