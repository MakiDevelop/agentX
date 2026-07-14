"""Importable runtime slash handlers used by ``run_shell()``.

These implement the real interactive-shell logic for a small set of
commands (``/plan``, ``/execute``, ``/mode``, plus read-only tool-backed
``/files``, ``/read``, ``/search``, ``/git``, ``/diff``). Nested handlers
inside ``cli.run_shell()`` should delegate here so unit tests can exercise
the same path without driving the full interactive loop.

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

# Transcript content truncation used by historical run_shell tool handlers.
_TOOL_TRANSCRIPT_LIMIT = 2000


def _run_tool_slash(
    *,
    command: str,
    tool_name: str,
    tool_args: dict[str, Any],
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
    fail_prefix: str,
    transcript_extra: dict[str, Any] | None = None,
) -> None:
    """Shared path: tools.run → transcript tool event → emit success/failure text.

    ``emit`` should be the same sink nested handlers used (``print_tool_result``),
    so empty-output formatting stays in the shell layer.
    """
    result = tools.run(tool_name, tool_args)
    payload: dict[str, Any] = {"command": command}
    if transcript_extra:
        payload.update(transcript_extra)
    payload.update(
        {
            "ok": result.ok,
            "content": result.content[:_TOOL_TRANSCRIPT_LIMIT],
        }
    )
    transcript.write("tool", payload)
    emit(result.content if result.ok else f"{fail_prefix}{result.content}")


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


# --- read-only tool-backed slash handlers ---------------------------------


def handle_files(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """List repo files (default ``.``)."""
    path = prompt.removeprefix("/files").strip() or "."
    _run_tool_slash(
        command="/files",
        tool_name="list_files",
        tool_args={"path": path},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="工具執行失敗：",
    )


def handle_read(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Read a single file under the workspace."""
    path = prompt.removeprefix("/read ").strip()
    _run_tool_slash(
        command="/read",
        tool_name="read_file",
        tool_args={"path": path},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="讀取失敗：",
        transcript_extra={"path": path},
    )


def handle_search(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Search text in the workspace (pattern only; no extra transcript fields)."""
    pattern = prompt.removeprefix("/search ").strip()
    _run_tool_slash(
        command="/search",
        tool_name="search_text",
        tool_args={"pattern": pattern},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="搜尋失敗：",
    )


def handle_git(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Show git status. Extra args on the slash line are ignored (historical)."""
    _ = prompt
    _run_tool_slash(
        command="/git",
        tool_name="git_status",
        tool_args={},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="工具執行失敗：",
    )


def handle_diff(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Show git diff; optional path after ``/diff``."""
    path = prompt.removeprefix("/diff").strip()
    args: dict[str, Any] = {"path": path} if path else {}
    _run_tool_slash(
        command="/diff",
        tool_name="git_diff",
        tool_args=args,
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="工具執行失敗：",
        transcript_extra={"path": path},
    )
