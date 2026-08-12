#!/usr/bin/env python3
"""Measure how reliably a local model drives the agentX protocol.

    uv run python scripts/run_local_benchmark.py --model gemma4:31b
    uv run python scripts/run_local_benchmark.py --model qwen3.6:35b --json out.json

Needs a reachable Ollama. This is an instrument, not a gate: run it before and
after a prompt or loop change and compare. Results are only comparable across
runs when the case set and system prompt construction are identical, so both
live in agentx.benchmark rather than being assembled here.

Worked example — the change that moved the tool list from a hand-written block
to one generated from the ToolRegistry, measured on gemma4:31b:

    expectation_match   0.636  ->  0.818

The first six cases showed 1.000 for both prompts: the model guessed common
tool names correctly even when the prompt omitted them. Only cases naming tools
whose existence cannot be guessed (docker_compose_ps, web_fetch) separated the
two. A benchmark that cannot fail cannot tell you anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentx.benchmark import run_benchmark  # noqa: E402
from agentx.ollama import OllamaClient  # noqa: E402
from agentx.runtime_prompt import build_headless_agent_system_prompt  # noqa: E402
from agentx.tools import ToolRegistry, builtin_tools  # noqa: E402


class _NullMemory:
    def search(self, *args: object, **kwargs: object) -> str:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Ollama model tag, e.g. gemma4:31b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--json", dest="json_out", help="Write the full report to this path")
    args = parser.parse_args()

    registry = ToolRegistry(
        builtin_tools(REPO_ROOT, _NullMemory()),  # type: ignore[arg-type]
        auto_approve_yellow=True,
    )
    known_tools = set(registry.names()) | {"task_add", "task_update", "task_list"}
    system_prompt = build_headless_agent_system_prompt(tools=registry)

    client = OllamaClient(args.base_url, args.model, timeout=args.timeout)
    report = run_benchmark(
        client,
        system_prompt,
        known_tools,
        model=args.model,
        base_url=args.base_url,
    )
    payload = report.payload()

    metrics = payload["metrics"]
    print(f"model: {args.model}  ({payload['case_count']} cases)")
    for key, value in metrics.items():
        print(f"  {key:28s} {value}")

    misses = [c for c in payload["cases"] if not c["matched_expectation"]]
    if misses:
        print(f"\n{len(misses)} case(s) did not match expectation:")
        for case in misses:
            print(f"  - {case['case']}: type={case['action_type']} tool={case['tool']}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nfull report -> {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
