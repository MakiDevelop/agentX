from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Any

import httpx

from .chat_turn import ChatTurn, NativeToolCall
from .provider_registry import register_llm_backend


class OllamaCancelledError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        # Ollama reports how many tokens its own tokenizer produced for the
        # prompt it just processed. That is exact, free, and was previously
        # thrown away while the context budget guessed from character counts.
        # 0 means "not reported by this response", never "the prompt was empty".
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        return self.chat_turn(
            messages,
            json_mode=json_mode,
            on_delta=on_delta,
            cancel_event=cancel_event,
            tools=tools,
        ).content

    def chat_turn(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": on_delta is not None or cancel_event is not None,
        }
        # Native tools and JSON-mode are mutually exclusive: format=json
        # forces a content string and silently drops tool_calls.
        if tools:
            payload["tools"] = list(tools)
        elif json_mode:
            payload["format"] = "json"
        if payload["stream"]:
            return self._chat_stream(payload, on_delta, cancel_event)
        response = self._client.post(f"{self.base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        self._record_usage(data)
        return _turn_from_message(data.get("message") or {})

    def _chat_stream(
        self,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> ChatTurn:
        chunks: list[str] = []
        collected_calls: list[NativeToolCall] = []
        with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise OllamaCancelledError("Ollama request cancelled")
                if not line:
                    continue
                data = json.loads(line)
                message = data.get("message") or {}
                delta = str(message.get("content") or "")
                if delta:
                    chunks.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
                collected_calls.extend(_parse_tool_calls(message.get("tool_calls")))
                if data.get("done"):
                    # Usage counts only appear on the final streamed chunk.
                    self._record_usage(data)
                    break
        return ChatTurn(content="".join(chunks).strip(), tool_calls=tuple(collected_calls))

    def _record_usage(self, data: dict[str, Any]) -> None:
        self.last_prompt_tokens = _int_or_zero(data.get("prompt_eval_count"))
        self.last_completion_tokens = _int_or_zero(data.get("eval_count"))

    def list_models(self) -> list[str]:
        response = self._client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [str(model.get("name", "")) for model in data.get("models", []) if model.get("name")]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaClient:
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


def _turn_from_message(message: dict[str, Any]) -> ChatTurn:
    return ChatTurn(
        content=str(message.get("content") or "").strip(),
        tool_calls=tuple(_parse_tool_calls(message.get("tool_calls"))),
    )


def _parse_tool_calls(raw: object) -> list[NativeToolCall]:
    if not isinstance(raw, list):
        return []
    calls: list[NativeToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        calls.append(NativeToolCall(name=name, arguments=_coerce_arguments(function.get("arguments"))))
    return calls


def _coerce_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _int_or_zero(value: object) -> int:
    """Usage fields are absent on some responses and on older Ollama builds."""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# Self-register with the provider registry so that simply importing
# agentx.ollama makes the "ollama" backend available.
register_llm_backend("ollama", OllamaClient)
