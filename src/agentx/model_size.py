"""Decide whether the loaded local model needs small-model scaffolding.

The old harness treated every `gemma*` name as a weak 2B-class model and
injected a 200-line micro-step ritual. gemma4:31b is a 31B model. That
ritual is the opposite of how Claude Code / Codex / Grok CLI drive a
capable model: they give tools and a short contract, then let it work.
"""

from __future__ import annotations

import re

# Explicit small / large tags beat a raw parameter-count guess.
_SMALL_NAME_MARKERS = (
    "tiny",
    "mini",
    "small",
    "gemma2",
    "gemma:2b",
    "gemma:7b",
    "e2b",
    "e4b",
)
_LARGE_NAME_MARKERS = (
    "nemotron",
    "qwen3.6",
    "qwen3:",
    "gpt-oss",
    "deepseek",
    "command-r",
    "mistral-large",
    "llama4",
    "gemma4",
)

_PARAM_RE = re.compile(r"(?:^|[:/\-_.])(\d{1,3})b\b", re.IGNORECASE)


def is_small_local_model(model: str | None) -> bool:
    """True only when the model is actually small enough to need extra ritual."""
    if not isinstance(model, str) or not model.strip():
        return False
    name = model.strip().lower()
    if any(marker in name for marker in _LARGE_NAME_MARKERS):
        params = _parameter_billions(name)
        return params is not None and params < 15
    if any(marker in name for marker in _SMALL_NAME_MARKERS):
        return True
    params = _parameter_billions(name)
    if params is None:
        return False
    return params < 15


def _parameter_billions(name: str) -> int | None:
    match = _PARAM_RE.search(name)
    if not match:
        return None
    return int(match.group(1))
