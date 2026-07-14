"""Shared test helpers for agentX unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentx.config import Settings


def make_settings(
    workspace: Path,
    *,
    max_steps: int = 5,
    context_limit_tokens: int = 8192,
    learning_enabled: bool = True,
    **overrides: Any,
) -> Settings:
    """Build a minimal Settings for tests.

    Defaults match the common fake-stack used across session / coordinator /
    CLI tests. Override only the fields a test cares about.
    """
    values: dict[str, Any] = {
        "model": "fake",
        "ollama_url": "http://localhost:11434",
        "ollama_timeout": 60.0,
        "memory_hall_url": "http://localhost:9100",
        "memory_hall_token": None,
        "max_steps": max_steps,
        "context_limit_tokens": context_limit_tokens,
        "auto_handoff": False,
        "persona": "default",
        "workspace": workspace,
        "learning_enabled": learning_enabled,
    }
    values.update(overrides)
    return Settings.from_values(**values)
