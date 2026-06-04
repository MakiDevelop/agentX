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
        for fixer in (_fix_invalid_escapes, _fix_common_malformed_json):
            try:
                data = json.loads(fixer(candidate))
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
    s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', s)
    # Fix invalid escape sequences inside JSON strings (common with code-in-JSON)
    s = _fix_invalid_escapes(s)
    return s


def _fix_invalid_escapes(s: str) -> str:
    valid_escapes = frozenset('"\\/bfnrtu')
    result = []
    i = 0
    in_string = False
    while i < len(s):
        ch = s[i]
        if ch == '"' and (i == 0 or s[i - 1] != '\\'):
            in_string = not in_string
            result.append(ch)
        elif ch == '\\' and in_string and i + 1 < len(s):
            next_ch = s[i + 1]
            if next_ch in valid_escapes:
                result.append(ch)
            else:
                result.append('\\\\')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


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
