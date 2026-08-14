"""Decide whether a user turn needs tools.

Chat mode cannot call tools. The 2026-08-12 crawler session died there:
the model kept asking Maki to type /mode agent instead of doing the work.
If the text is a tool task, the shell must escalate itself.
"""

from __future__ import annotations

import os
import re

# Completion guard: the user asked for a file change, not just an explanation.
MUTATION_INTENT = re.compile(
    r"(幫我寫|寫一支|寫一個|寫一份|建立(?:一個)?檔|新增檔|實作|"
    r"create (?:a |the )?(?:file|script|crawler|module)|"
    r"implement |write (?:a |the )?(?:file|script|crawler))",
    re.IGNORECASE,
)

# Broader than mutation: inspect / fetch / debug also need the agent loop.
_TOOL_INTENT = re.compile(
    r"(幫我寫|寫一支|寫一個|寫一份|建立(?:一個)?檔|新增檔|實作|"
    r"幫我改|幫我修|幫我看|讀一下|搜一下|抓取|爬蟲|"
    r"create (?:a |the )?(?:file|script|crawler|module)|"
    r"implement |write (?:a |the )?(?:file|script|crawler)|"
    r"fix (?:the |this )|edit (?:the |this )|debug )",
    re.IGNORECASE,
)

_CHAT_STAY = re.compile(
    r"^(你是誰|你好|hi\b|hello\b|什麼是|為什麼|怎麼用|如何使用|解釋一下|幫我解釋)\b",
    re.IGNORECASE,
)


def should_use_agent(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if _CHAT_STAY.search(text):
        return False
    return bool(_TOOL_INTENT.search(text) or MUTATION_INTENT.search(text))


# Explicit "split this work" language. These always go to the orchestrator.
_ORCH_EXPLICIT = re.compile(
    r"(拆成子任務|分成子任務|分階段做|用 orchestrat|開 orchestrat|"
    r"plan then (?:split|execute)|multi-agent)",
    re.IGNORECASE,
)

# Multi-module / multi-phase engineering. Conservative on purpose:
# "幫我寫一支爬蟲" must stay on the single-agent loop.
_ORCH_COMPLEX = re.compile(
    r"(重構|遷移|整個模組|整套|多檔|多個檔案|end-to-end|end to end|"
    r"refactor|migrate|"
    r"先.{0,24}再.{0,24}(?:然後|最後))",
    re.IGNORECASE,
)

_NUMBERED_STEP = re.compile(r"(?:^|\n)\s*(?:\d+[\.\)、])\s+\S+")
_PATH_TOKEN = re.compile(
    r"(?:[\w.-]+/)+[\w.-]+\.\w+|[\w.-]+\.(?:py|ts|tsx|js|go|rs|toml|md)"
)


def should_orchestrate(prompt: str) -> bool:
    """True when a single agent loop is the wrong shape for this request."""
    text = (prompt or "").strip()
    if not text or _CHAT_STAY.search(text):
        return False
    if _ORCH_EXPLICIT.search(text):
        return True
    if len(_NUMBERED_STEP.findall(text)) >= 3:
        return True
    paths = set(_PATH_TOKEN.findall(text))
    if len(paths) >= 3 and should_use_agent(text):
        return True
    if _ORCH_COMPLEX.search(text):
        if len(paths) >= 2:
            return True
        if "測試" in text or re.search(r"\btests?\b", text):
            return True
        if should_use_agent(text):
            return True
    return False


def auto_orchestrate_enabled() -> bool:
    return os.getenv("AGENTX_AUTO_ORCHESTRATE", "1") != "0"


def should_auto_orchestrate(
    prompt: str,
    *,
    agent_mode: bool,
    plan_mode: bool = False,
    plan_then_execute: bool = False,
    resume: bool = False,
    force: bool = False,
) -> bool:
    """Headless / shell gate. ``--orchestrate`` is force; plan/resume never auto."""
    if force:
        return True
    if not agent_mode or plan_mode or plan_then_execute or resume:
        return False
    if not auto_orchestrate_enabled():
        return False
    return should_orchestrate(prompt)
