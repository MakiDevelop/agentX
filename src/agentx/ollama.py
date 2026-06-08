from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Any

import httpx

from .provider_registry import register_llm_backend


class OllamaCancelledError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

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
        if payload["stream"]:
            return self._chat_stream(payload, on_delta, cancel_event)
        response = self._client.post(f"{self.base_url}/api/chat", json=payload)
        response.raise_for_status()
        return _message_content(response.json()).strip()

    def _chat_stream(
        self,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> str:
        chunks: list[str] = []
        with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
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
        response = self._client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [str(model.get("name", "")) for model in data.get("models", []) if model.get("name")]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _message_content(data: dict[str, Any]) -> str:
    return str(data.get("message", {}).get("content", ""))


# Self-register with the provider registry so that simply importing
# agentx.ollama makes the "ollama" backend available.
register_llm_backend("ollama", OllamaClient)