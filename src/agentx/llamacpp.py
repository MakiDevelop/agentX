from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from typing import Any

import httpx


class LlamaCppCancelledError(RuntimeError):
    pass


class LlamaCppClient:
    """LLM client for llama.cpp's OpenAI-compatible API (/v1/chat/completions)."""

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
        stream = on_delta is not None or cancel_event is not None
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    if stream:
                        return self._chat_stream(client, payload, on_delta, cancel_event)
                    response = client.post(
                        f"{self.base_url}/v1/chat/completions", json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                return _extract_content(data).strip()
            except httpx.ReadTimeout:
                if attempt == 2:
                    raise
                continue

    def _chat_stream(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> str:
        chunks: list[str] = []
        with client.stream(
            "POST", f"{self.base_url}/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise LlamaCppCancelledError("llama.cpp request cancelled")
                if not line:
                    continue
                # SSE format: "data: {...}" or "data: [DONE]"
                if line.startswith("data: "):
                    line = line[6:]
                if line.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = _extract_stream_delta(data)
                if delta:
                    chunks.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
        return "".join(chunks).strip()

    def list_models(self) -> list[str]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{self.base_url}/v1/models")
            response.raise_for_status()
            data = response.json()
        return [
            str(m.get("id", ""))
            for m in data.get("data", [])
            if m.get("id")
        ]


def _extract_content(data: dict[str, Any]) -> str:
    """Extract content from a non-streaming response."""
    choices = data.get("choices", [])
    if not choices:
        return ""
    return str(choices[0].get("message", {}).get("content", ""))


def _extract_stream_delta(data: dict[str, Any]) -> str:
    """Extract content delta from a streaming chunk."""
    choices = data.get("choices", [])
    if not choices:
        return ""
    return str(choices[0].get("delta", {}).get("content", ""))
