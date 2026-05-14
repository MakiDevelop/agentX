from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data.get("message", {}).get("content", "")).strip()

