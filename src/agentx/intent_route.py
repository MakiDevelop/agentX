"""Decide whether a user turn needs tools.

Chat mode cannot call tools. The 2026-08-12 crawler session died there:
the model kept asking Maki to type /mode agent instead of doing the work.
If the text is a tool task, the shell must escalate itself.
"""

from __future__ import annotations

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
