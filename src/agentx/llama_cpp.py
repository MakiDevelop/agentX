from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Any

import httpx


class LlamaCppClient:
    """OpenAI-compatible client for llama.cpp server.

    Drop-in replacement for OllamaClient — same chat() interface.
    """

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
            payload["response_format"] = {"type": "json_object"}
        if payload["stream"]:
            return self._chat_stream(payload, on_delta, cancel_event)
        for attempt in range(3):
            try:
                response = self._client.post(
                    f"{self.base_url}/v1/chat/completions", json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return _extract_content(data).strip()
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as e:
                if attempt == 2:
                    raise
                import time
                time.sleep(2 ** attempt)
        return ""

    def _chat_stream(
        self,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> str:
        chunks: list[str] = []
        with self._client.stream(
            "POST", f"{self.base_url}/v1/chat/completions", json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    from agentx.ollama import OllamaCancelledError
                    raise OllamaCancelledError("Request cancelled")
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = _extract_delta(data)
                if delta:
                    chunks.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
        return "".join(chunks).strip()

    def list_models(self) -> list[str]:
        response = self._client.get(f"{self.base_url}/v1/models")
        response.raise_for_status()
        data = response.json()
        models = data.get("data") or data.get("models") or []
        return [m.get("id", "") for m in models if m.get("id")]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LlamaCppClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    return str(choices[0].get("message", {}).get("content", ""))


def _extract_delta(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    return str(choices[0].get("delta", {}).get("content", ""))
