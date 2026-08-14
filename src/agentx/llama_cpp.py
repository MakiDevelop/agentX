from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Any

import httpx

from .chat_turn import ChatTurn, NativeToolCall
from .provider_registry import register_llm_backend
from .sse import iterate_sse_messages


class LlamaCppClient:
    """OpenAI-compatible client for llama.cpp server.

    Drop-in replacement for OllamaClient — same chat() interface.
    """

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(timeout=httpx.Timeout(timeout, read=max(timeout, 600.0)))

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
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if tools:
            payload["tools"] = list(tools)
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        if payload["stream"]:
            return self._chat_stream(payload, on_delta, cancel_event)
        for attempt in range(3):
            try:
                response = self._client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return _turn_from_completion(data)
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout):
                if attempt == 2:
                    raise
                import time

                time.sleep(2**attempt)
        return ChatTurn()

    def _chat_stream(
        self,
        payload: dict[str, Any],
        on_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> str:
        """Streaming implementation using the zero-dep SSE parser.

        This integrates the SSE reference (from BORROW-FROM-PI LOW item)
        into the actual OpenAI-compatible streaming path (llama.cpp /v1/chat/completions).
        It is more robust than the previous manual "data: " stripping:
        - Proper handling of \r\n / \r / \n endings
        - Ignores comment lines (: ...)
        - Correct multi-line data accumulation
        - Clean event separation on blank lines
        """
        chunks: list[str] = []
        with self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()
            for event in iterate_sse_messages(response.iter_lines()):
                if cancel_event is not None and cancel_event.is_set():
                    from agentx.ollama import OllamaCancelledError

                    raise OllamaCancelledError("Request cancelled")
                data_str = event.get("data", "").strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = _extract_delta(data)
                if delta:
                    chunks.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
        return ChatTurn(content="".join(chunks).strip())

    def list_models(self) -> list[str]:
        response = self._client.get(f"{self.base_url}/v1/models")
        response.raise_for_status()
        data = response.json()
        models = data.get("data") or data.get("models") or []
        return [m.get("id", "") for m in models if m.get("id")]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LlamaCppClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


# Self-register with the provider registry so that simply importing
# agentx.llama_cpp makes the "llama_cpp" backend available.
register_llm_backend("llama_cpp", LlamaCppClient)


def _extract_content(data: dict[str, Any]) -> str:
    return _turn_from_completion(data).content


def _turn_from_completion(data: dict[str, Any]) -> ChatTurn:
    choices = data.get("choices", [])
    if not choices:
        return ChatTurn()
    msg = choices[0].get("message", {}) or {}
    content = msg.get("content") or msg.get("reasoning_content") or ""
    return ChatTurn(
        content=str(content).strip(),
        tool_calls=tuple(_parse_openai_tool_calls(msg.get("tool_calls"))),
    )


def _parse_openai_tool_calls(raw: object) -> list[NativeToolCall]:
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
        arguments = function.get("arguments")
        parsed: dict[str, Any] = {}
        if isinstance(arguments, dict):
            parsed = dict(arguments)
        elif isinstance(arguments, str) and arguments.strip():
            try:
                loaded = json.loads(arguments)
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                parsed = loaded
        calls.append(NativeToolCall(name=name, arguments=parsed))
    return calls


def _extract_delta(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    return str(choices[0].get("delta", {}).get("content", ""))
