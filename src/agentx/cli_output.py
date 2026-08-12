"""Shared output primitives for the CLI.

Tiny — four names, a dozen lines — but **71 of cli.py's functions depend on
them**, which made them the single biggest obstacle to splitting that file: any
group extracted while these still lived in cli.py had to import back into
cli.py, i.e. was not closed.

Pulling the seam out first is what makes the other slices possible. See
`docs/CLI_SPLIT_PLAN.md` and `scripts/find_closed_groups.py`.

Two distinct output paths live here on purpose:

- `console` (Rich) writes human-facing tables and panels. It is width-aware and
  may colour or wrap.
- `print_json_output` writes machine-facing payloads straight to stdout with no
  Rich involvement at all. Runner output must never be wrapped, truncated or
  coloured — a JSON document that Rich decided to line-break at column 80 is not
  parseable, and Rich's behaviour depends on the terminal, so the bug would
  appear only on some machines. (agentX has been bitten by exactly this class of
  environment-dependent output twice: see `agentx.proc` and `tests/conftest.py`.)
"""

from __future__ import annotations

import json
import sys

from rich.console import Console

__all__ = [
    "console",
    "print_json_output",
    "print_structured_payload",
    "structured_payload_text",
]

#: Human-facing output. Not for anything a runner parses.
console = Console()


def print_json_output(text: str) -> None:
    """Write machine-facing output verbatim.

    Deliberately `sys.stdout`, not `console.print`: Rich would apply width-aware
    wrapping and markup interpretation to a document that must survive byte for
    byte.
    """
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


def structured_payload_text(
    payload: object, *, output_format: str = "json", event: str = "result"
) -> str:
    """Render a payload as JSON, or as one JSONL event envelope.

    `ensure_ascii=False` so Traditional Chinese stays readable in artifacts and
    logs rather than becoming `\\uXXXX` escapes — which also keeps the byte size
    (and the token cost, when a payload is fed back to a model) roughly 3x lower.
    """
    if output_format == "jsonl":
        return json.dumps({"event": event, "data": payload}, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def print_structured_payload(
    payload: object, *, output_format: str = "json", event: str = "result"
) -> None:
    print_json_output(structured_payload_text(payload, output_format=output_format, event=event))
