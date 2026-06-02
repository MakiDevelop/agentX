from __future__ import annotations

import json
import re
from typing import Any


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_object(raw: str) -> dict[str, Any] | None:
    candidates = []
    block_match = JSON_BLOCK_RE.search(raw)
    if block_match:
        candidates.append(block_match.group(1))
    candidates.append(raw)

    balanced = _first_balanced_object(raw)
    if balanced is not None:
        candidates.append(balanced)

    for candidate in candidates:
        # Gemma4 / small model common fixes before json.loads
        fixed = _fix_common_malformed_json(candidate)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _fix_common_malformed_json(s: str) -> str:
    """Heuristic fixes for JSON produced by smaller models like Gemma4.
    - Remove trailing commas before } or ]
    - Convert single quotes to double (for strings and keys, best-effort)
    - Remove JS-style comments
    - Trim leading/trailing junk
    This increases tool-call parse success rate without changing the strict prompt contract.
    """
    if not s or not s.strip():
        return s
    s = s.strip()
    # Remove // and /* */ comments (small models sometimes add them)
    s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    # Remove trailing commas ( ,} or ,] )
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Best-effort single to double quotes for keys and string values
    # Only do simple cases to avoid breaking valid JSON with escaped quotes.
    # This is defense-in-depth; the prompt still requires proper double-quoted JSON.
    s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', s)
    return s


def _first_balanced_object(raw: str) -> str | None:
    start = raw.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(raw[start:], start=start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    return None
