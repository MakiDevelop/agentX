"""Zero-dependency SSE (Server-Sent Events) parser.

This is a reference implementation prepared for future direct use of
Anthropic / OpenAI streaming APIs without their official SDKs (bypassing
SDK-level buffering or parsing).

Borrowed/adapted from earendil-works/pi (the hand-written parser in their
Anthropic provider, specifically functions like iterateSseMessages,
decodeSseLine, and consumeLine).

Key features ported / ensured:
- Correctly handles \n, \r, and \r\n line endings.
- Ignores comment lines (starting with ':').
- Supports multi-line `data:` fields (accumulated with \n between parts).
- Parses standard fields: event, data, id, retry.
- Yields complete events only when a blank line (event delimiter) is seen.

Current agentX usage:
- We primarily use Ollama (JSON line streaming) and llama.cpp (OpenAI-compatible).
- This module is **not wired in** yet (LOW priority, "目前不需要").
- It is left as a clean, self-contained reference so we can pull it in later
  when we want to speak raw SSE to providers that only expose SSE (or when
  we want to avoid SDK bloat / version skew).

Example future usage:
    import httpx
    from agentx.sse import iterate_sse_messages

    with httpx.stream("POST", url, ...) as r:
        for event in iterate_sse_messages(r.iter_lines()):
            if event.get("event") == "message" or "data" in event:
                handle(event["data"])
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


def _normalize_line_endings(data: str | bytes) -> list[str]:
    """Split on any of \r\n, \r, \n while preserving empty event delimiters."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    # Normalize all common line endings to \n for splitting, but keep
    # empty lines as delimiters.
    data = data.replace("\r\n", "\n").replace("\r", "\n")
    return data.split("\n")


def decode_sse_line(line: str) -> tuple[str, str] | None:
    """Decode a single SSE field line.

    Returns (field, value) or None for comment/empty lines.
    Matches the spirit of pi's decodeSseLine.
    """
    line = line.rstrip("\r\n")
    if not line or line.startswith(":"):
        return None  # comment or empty
    if ":" not in line:
        return (line, "")
    field, value = line.split(":", 1)
    if value.startswith(" "):
        value = value[1:]
    return (field, value)


def consume_line(buffer: list[str], line: str) -> dict[str, Any] | None:
    """Process one line into the current event buffer.

    Returns a complete event dict when a blank line (event delimiter) is
    encountered, otherwise None. Matches pi's consumeLine intent.
    """
    parsed = decode_sse_line(line)
    if parsed is None:
        # blank line -> end of event
        if buffer:
            event: dict[str, Any] = {}
            data_parts: list[str] = []
            for field, value in buffer:
                if field == "data":
                    data_parts.append(value)
                else:
                    event[field] = value
            if data_parts:
                event["data"] = "\n".join(data_parts)
            buffer.clear()
            return event
        return None

    field, value = parsed
    buffer.append((field, value))
    return None


def iterate_sse_messages(lines: Iterable[str | bytes]) -> Iterator[dict[str, Any]]:
    """Main generator. Yields complete SSE events as dicts.

    This is the primary entry point (analogous to pi's iterateSseMessages).

    Usage with httpx:
        with httpx.stream(...) as response:
            for event in iterate_sse_messages(response.iter_lines()):
                ...

    The parser is intentionally minimal and has zero dependencies.
    """
    buffer: list[tuple[str, str]] = []
    for raw in lines:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        # Split the (possibly multi-line after normalization) chunk
        for line in _normalize_line_endings(raw):
            event = consume_line(buffer, line)
            if event is not None:
                yield event


# Convenience: parse a whole string/blob at once (useful for tests or small responses)
def parse_sse(data: str | bytes) -> list[dict[str, Any]]:
    """Parse a complete SSE payload and return all events."""
    return list(iterate_sse_messages([data]))
