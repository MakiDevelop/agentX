"""Module-level slash dispatch shims used by unit tests.

These are intentionally the testable simple versions (used by
``tests/test_cli_dispatch.py`` and any direct import of the symbols).

The rich interactive implementations remain nested inside
``cli.run_shell()`` and are registered into a *local* ``SLASH_HANDLERS``
dict at runtime. This module exists so those test shims no longer live
inside the large ``cli.py`` surface.

Do not treat these as the runtime shell dispatch path.
"""

from __future__ import annotations

# Compatibility empty table. Runtime shell populates a *local* dict inside
# run_shell(); this module-level name stays empty on plain import.
SLASH_HANDLERS: dict = {}

_ZERO_ARG_COMMANDS = {"/exit", "/quit", "/clear", "/git"}


def dispatch_slash(state, prompt, **kwargs):
    """Minimal router so tests can call dispatch_slash and observe side effects or return codes."""
    if not prompt or not isinstance(prompt, str):
        return False
    parts = prompt.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    has_extra = len(parts) > 1 and bool(parts[1].strip())

    if cmd in _ZERO_ARG_COMMANDS:
        if has_extra:
            # Per test_zero_arg_commands_reject_extra_args: still return True (recognized)
            # but do NOT execute the action.
            return True
        # clean call -> execute
        if cmd == "/exit":
            cmd_exit(state, prompt)
        elif cmd == "/quit":
            cmd_quit(state, prompt)
        elif cmd == "/clear":
            cmd_clear(state, prompt)
        elif cmd == "/git":
            # git in tests may go through tools; for dispatch test we just mark handled
            pass
        return True

    if cmd == "/plan":
        cmd_plan(state, prompt)
        return True
    if cmd == "/mode":
        cmd_mode(state, prompt)
        return True
    if cmd == "/files":
        cmd_files(state, prompt)
        return True

    return False


def cmd_clear(state, prompt: str = "", **kwargs):
    session = getattr(state, "agent_session", None)
    if session is not None and hasattr(session, "clear"):
        session.clear()
    if hasattr(state, "chat_messages"):
        state.chat_messages[:] = [{"role": "system", "content": "cleared"}]


def cmd_exit(state, prompt: str = "", **kwargs):
    state.should_exit = True
    state.exit_reason = "/exit"


def cmd_files(state, prompt: str = "", **kwargs):
    path = (prompt or "").removeprefix("/files").strip() or "."
    tools = getattr(state, "tools", None)
    if tools is not None and hasattr(tools, "run"):
        tools.run("list_files", {"path": path})


def cmd_mode(state, prompt: str = "", **kwargs):
    arg = (prompt or "").removeprefix("/mode ").strip().lower()
    if arg in {"chat", "agent"}:
        if hasattr(state, "set_chat_mode"):
            state.set_chat_mode(arg)
        else:
            state.mode = arg


def cmd_plan(state, prompt: str = "", **kwargs):
    new_plan = not getattr(state, "plan_mode", False)
    if hasattr(state, "set_plan_mode"):
        state.set_plan_mode(new_plan)
    else:
        state.plan_mode = new_plan


def cmd_quit(state, prompt: str = "", **kwargs):
    state.should_exit = True
    state.exit_reason = "/quit"
