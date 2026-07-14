"""Importable runtime slash handlers used by ``run_shell()``.

These implement the real interactive-shell logic for a small set of
commands (``/plan``, ``/execute``, ``/mode``, plus read-only tool-backed
``/files``, ``/read``, ``/search``, ``/git``, ``/diff``, low-risk
tool-backed ``/memory``, ``/fetch``, ``/run``, ``/test``, low-risk
inspection handlers ``/status``, ``/sessions``, ``/jobs``, the read-only
``/task`` empty/status/list branch, and pure info/display handlers
``/help``, ``/guide``, ``/workflows``, ``/tools``, ``/context``,
``/history``, ``/transcript``). Nested handlers inside ``cli.run_shell()``
should delegate here so unit tests can exercise the same path without
driving the full interactive loop.

Do not confuse with ``cli_slash_shims`` — those are simplified test-only
dispatch stubs and are *not* the runtime shell path.

Side-effect branches (``/cancel``, ``/task add|update|done|clear``,
``/apply``, ``/commit``, ``/docker``, ``/clear``, ``/compact``,
``/resume``, ``/handoff``, ``/attach``) stay in ``cli.py``.
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
# Longer limit used by /fetch, /run, /test (historical run_shell values).
_TOOL_TRANSCRIPT_LIMIT_LONG = 4000


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
    transcript_limit: int = _TOOL_TRANSCRIPT_LIMIT,
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
            "content": result.content[:transcript_limit],
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


# --- low-risk tool-backed handlers (/memory /fetch /run /test) ------------


def handle_memory(
    state: Any,
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
    emit_usage: Callable[[str], None] | None = None,
) -> None:
    """Search Memory Hall for the current namespace (``/memory QUERY``).

    Writes a ``slash_command`` event first (historical). Empty query after
    ``/memory`` or ``/memory `` emits usage and returns without calling the tool.
    Transcript tool content is truncated to 2000 chars.
    """
    usage_emit = emit_usage if emit_usage is not None else emit
    transcript.write("slash_command", {"command": prompt})
    query = prompt.removeprefix("/memory").strip()
    if not query:
        usage_emit("usage: /memory QUERY")
        return
    _run_tool_slash(
        command="/memory",
        tool_name="memory_search",
        tool_args={"query": query, "namespace": state.namespace},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="memory search failed: ",
        transcript_extra={"query": query},
        transcript_limit=_TOOL_TRANSCRIPT_LIMIT,
    )


def handle_fetch(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Fetch external URL text via ``web_fetch`` (transcript limit 4000)."""
    url = prompt.removeprefix("/fetch ").strip()
    _run_tool_slash(
        command="/fetch",
        tool_name="web_fetch",
        tool_args={"url": url},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="fetch failed: ",
        transcript_extra={"url": url},
        transcript_limit=_TOOL_TRANSCRIPT_LIMIT_LONG,
    )


def handle_run(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Run an allowlisted command via ``run_command`` (transcript limit 4000)."""
    command = prompt.removeprefix("/run ").strip()
    _run_tool_slash(
        command="/run",
        tool_name="run_command",
        tool_args={"command": command},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="run failed: ",
        transcript_extra={"input": command},
        transcript_limit=_TOOL_TRANSCRIPT_LIMIT_LONG,
    )


def handle_test(
    prompt: str,
    *,
    tools: Any,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Run fixed allowlist verification via ``run_tests`` (transcript limit 4000)."""
    _ = prompt
    _run_tool_slash(
        command="/test",
        tool_name="run_tests",
        tool_args={},
        tools=tools,
        transcript=transcript,
        emit=emit,
        fail_prefix="驗證失敗：",
        transcript_limit=_TOOL_TRANSCRIPT_LIMIT_LONG,
    )


# --- low-risk inspection handlers -----------------------------------------


def handle_status(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    emit: Callable[[str], None],
    approval_mode: str,
    message_count: int,
    format_status: Callable[[bool], str],
    collect_aca_probe_info: Callable[[Any, Any], dict[str, Any]] | None = None,
    emit_panel: Callable[[str, str], None] | None = None,
) -> None:
    """Show model/mode/plan/approval/namespace/persona/context/messages (+ ACA probe).

    ``emit_panel(content, title)`` is used for the ACA audit events panel when
    probe data is available. ``collect_aca_probe_info`` is injected so the
    shell-layer collector (shared with /config and /doctor) stays in ``cli.py``.
    """
    transcript.write("slash_command", {"command": prompt})
    approx_tokens = state.agent_session.context_chars // 4 if state.agent_session else 0
    plan_status = format_status(state.plan_mode)

    # Show approval posture for better safety awareness (vision alignment)
    approval_display = approval_mode or "ask"
    safety_note = {
        "auto": "YELLOW 自動執行",
        "ask": "YELLOW 會詢問",
        "off": "YELLOW 受限",
    }.get(approval_display, approval_display)

    emit(
        f"model={state.settings.model}  mode={state.mode}  plan={plan_status}\n"
        f"approval={approval_display} ({safety_note})  |  "
        f"namespace={state.namespace}  persona={state.settings.persona}\n"
        f"context ~{approx_tokens} tokens  |  messages={message_count}"
    )

    # ACA live conformance signals: make /status also show the complete
    # post-governance-record audit event list when probe data is available.
    if collect_aca_probe_info is None:
        return
    try:
        mem = getattr(state, "memory", None)
        if getattr(state.settings, "memory_backend", "memhall") == "amh" and mem is not None:
            pinfo = collect_aca_probe_info(state.settings, mem)
            if pinfo["client_type"] != "N/A":
                emit(
                    f"[dim]記憶 client: {pinfo['client_type']} | "
                    f"最新 probe 過期: {pinfo['latest_probe_expires'] or 'N/A'} | "
                    f"gov record: {pinfo['latest_probe_gov'] or 'N/A'}[/dim]"
                )
                gov_evs = pinfo.get("latest_probe_gov_audit_full")
                if gov_evs is not None and emit_panel is not None:
                    evs = gov_evs or []
                    formatted = []
                    for i, e in enumerate(evs, 1):
                        s = str(e).replace("\n", " | ")[:120]
                        formatted.append(f"{i}. {s}")
                    events_str = "\n".join(formatted) or "(none)"
                    events_str += (
                        "\n（已列出全部事件；長列表請向上捲動查看；完整列表亦見 /config 表格）"
                    )
                    emit_panel(
                        events_str,
                        "最新 probe gov audit events (ACA, 完整列表) — /status",
                    )
    except Exception:
        pass  # non-fatal for status display


def handle_sessions(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    print_sessions: Callable[[Any], None],
) -> None:
    """List recent transcripts; delegates rendering to ``print_sessions``."""
    transcript.write("slash_command", {"command": prompt})
    print_sessions(state.settings)


def handle_jobs(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    job_queue: Any,
    print_jobs: Callable[[Any], None],
) -> None:
    """Show job queue; delegates rendering to ``print_jobs``."""
    transcript.write("slash_command", {"command": prompt})
    print_jobs(job_queue)


def handle_task_readonly(
    value: str,
    *,
    tasks: list[dict[str, Any]],
    format_summary: Callable[[list[dict[str, Any]]], str],
    emit_panel: Callable[[str, str], None],
    emit: Callable[[str], None],
) -> bool:
    """Handle ``/task`` empty / status / list only.

    Returns True when this branch handled the command (caller should return).
    Write branches (add / update / done / clear / legacy free-text add) stay
    in ``cli.py``.
    """
    if value and value not in {"status", "list"}:
        return False

    summary = format_summary(tasks)
    emit_panel(summary, "Task List (多任務清單)")
    if tasks:
        emit("[dim]提示：使用 /task update <id> done|in_progress [notes] 來更新[/dim]")
    return True


# --- pure info / display handlers -----------------------------------------


def handle_help(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    print_slash_help: Callable[[], None],
) -> None:
    """Show slash-command help; rendering stays in the shell layer."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    print_slash_help()


def handle_guide(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    print_guide: Callable[[], None],
    mark_guide_hint_seen: Callable[[Any], None],
) -> None:
    """Show 60-second guide and mark the first-run hint as seen.

    ``mark_guide_hint_seen`` is injected so this module does not import
    ``project_state`` (or ``cli``); nested shell code passes the real
    ``mark_guide_hint_seen(state.settings.workspace)`` callback.
    """
    transcript.write("slash_command", {"command": prompt})
    mark_guide_hint_seen(state.settings.workspace)
    print_guide()


def handle_workflows(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    print_workflows: Callable[[], None],
) -> None:
    """Show practical workflow recipes."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    print_workflows()


def handle_tools(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    tools: Any,
    print_tools: Callable[[Any], None],
) -> None:
    """List available tools (risk grouping stays in ``print_tools``)."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    print_tools(tools)


def handle_context(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    agent_session: Any,
    chat_messages: Any,
    print_context: Callable[[Any, Any], None],
) -> None:
    """Show agent context usage; caller resolves which session to pass."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    print_context(agent_session, chat_messages)


def handle_history(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    history: Any,
    print_history: Callable[[Any], None],
) -> None:
    """Show short shell interaction history."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    print_history(history)


def handle_transcript(
    state: Any,
    prompt: str,
    *,
    transcript: Any,
    emit: Callable[[str], None],
) -> None:
    """Emit the current JSONL transcript path."""
    _ = state
    transcript.write("slash_command", {"command": prompt})
    emit(str(transcript.path))
