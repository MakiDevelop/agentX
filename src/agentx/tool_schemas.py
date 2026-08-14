"""Turn ToolRegistry metadata into provider-native tool schemas.

The system prompt still lists tools for models that only speak JSON-in-text.
Capable local models should receive the same tools as a structured
`tools` array (Ollama / OpenAI-compatible). Generating both from one
metadata source keeps them from drifting.
"""

from __future__ import annotations

import re
from typing import Any

from agentx.runtime_prompt import LOOP_PSEUDO_TOOLS

_SPLIT_PARAMS = re.compile(r",(?![^\[\]()]*[\]\)])(?=(?:[^']*'[^']*')*[^']*$)(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)")


def parse_signature(signature: str) -> tuple[dict[str, Any], list[str]]:
    """Parse a tool `signature` string into JSON-schema properties + required."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    text = (signature or "").strip()
    if not text:
        return properties, required
    for raw in _SPLIT_PARAMS.split(text):
        part = raw.strip()
        if not part:
            continue
        if "=" in part:
            name, default = part.split("=", 1)
            name = name.strip()
            if not name:
                continue
            properties[name] = _schema_for_default(default.strip())
            continue
        name = part.strip()
        if not name:
            continue
        properties[name] = {"type": "string"}
        required.append(name)
    return properties, required


def ollama_tools_from_registry(registry: Any | None) -> list[dict[str, Any]]:
    """Ollama / OpenAI-compatible `tools` array, plus loop pseudo-tools."""
    rows = _registry_rows(registry)
    tools = [_function_tool(name, description, signature) for name, description, signature in rows]
    for name, signature, description in LOOP_PSEUDO_TOOLS:
        tools.append(_function_tool(name, description, signature))
    return tools


def _function_tool(name: str, description: str, signature: str) -> dict[str, Any]:
    properties, required = parse_signature(signature)
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or name,
            "parameters": parameters,
        },
    }


def _registry_rows(registry: Any | None) -> list[tuple[str, str, str]]:
    if registry is None:
        return []
    describe = getattr(registry, "describe_tool_infos", None)
    if callable(describe):
        rows: list[tuple[str, str, str]] = []
        for info in describe() or []:
            rows.append(
                (
                    str(info.get("name") or ""),
                    str(info.get("description") or ""),
                    str(info.get("signature") or ""),
                )
            )
        return [row for row in rows if row[0]]
    listing = getattr(registry, "tools", None)
    if not callable(listing):
        return []
    rows = []
    for tool in listing() or []:
        name = str(getattr(tool, "name", "") or "")
        if not name:
            continue
        rows.append(
            (
                name,
                str(getattr(tool, "description", "") or ""),
                str(getattr(tool, "signature", "") or ""),
            )
        )
    return rows


def _schema_for_default(default: str) -> dict[str, Any]:
    text = default.strip()
    if not text:
        return {"type": "string"}
    if text[0] in "[{":
        return {"type": "array", "items": {"type": "object"}} if text[0] == "[" else {"type": "object"}
    if text.lower() in {"true", "false"}:
        return {"type": "boolean"}
    try:
        int(text)
        return {"type": "integer"}
    except ValueError:
        pass
    try:
        float(text)
        return {"type": "number"}
    except ValueError:
        pass
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return {"type": "string"}
    return {"type": "string"}
