from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from collections.abc import Callable
from typing import Any

import httpx


class OllamaCancelledError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": on_delta is not None or cancel_event is not None,
        }
        if json_mode:
            payload["format"] = "json"
        with httpx.Client(timeout=self.timeout) as client:
            if payload["stream"]:
                return self._chat_stream(client, payload, on_delta, cancel_event)
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return _message_content(data).strip()

    def _chat_stream(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> str:
        chunks: list[str] = []
        with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise OllamaCancelledError("Ollama request cancelled")
                if not line:
                    continue
                data = json.loads(line)
                delta = _message_content(data)
                if delta:
                    chunks.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
                if data.get("done"):
                    break
        return "".join(chunks).strip()

    def list_models(self) -> list[str]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
        return [str(model.get("name", "")) for model in data.get("models", []) if model.get("name")]


def _message_content(data: dict[str, Any]) -> str:
    return str(data.get("message", {}).get("content", ""))
