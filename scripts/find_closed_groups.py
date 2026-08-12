#!/usr/bin/env python3
"""Find groups of cli.py functions that can be extracted without entanglement.

    uv run python scripts/find_closed_groups.py
    uv run python scripts/find_closed_groups.py --prefix workflow

Splitting cli.py stalled once already (docs/CLI_DISPATCH_REFACTOR_HANDOFF.md,
stopped after four commands). The reason it is hard is not volume — it is that
picking the wrong group creates a circular import back into cli.py, and you only
find out after moving several hundred lines.

This answers the question mechanically. A group is **closed** when the transitive
closure of its call graph refers to nothing else defined at cli.py's top level.
A closed group can be moved verbatim; an open one needs its seams broken first.

Worked result (2026-08): the git/diff/patch group was closed at 12 functions /
454 lines and became cli_git.py. The workflow family — three times larger, and
the obvious choice by size — was NOT closed: it calls command_plan_payload,
inspect_payload, artifacts_payload and resolve_headless_workspace.
"""

from __future__ import annotations

import argparse
import ast
import itertools
import sys
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "src" / "agentx" / "cli.py"


def _is_command(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Typer commands are the CLI surface and stay put; only helpers move."""
    return any(
        getattr(getattr(dec, "func", dec), "attr", "") in {"command", "callback"}
        for dec in node.decorator_list
    )


def analyse(path: Path, prefixes: list[str]) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    consts = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    top_level = set(funcs) | consts

    deps = {
        name: {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id in top_level and child.id != name
        }
        for name, node in funcs.items()
    }

    def closure(seeds: set[str]) -> set[str]:
        seen, stack = set(seeds), list(seeds)
        while stack:
            for dep in deps.get(stack.pop(), ()):
                if dep in funcs and dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return seen

    def line_count(names: set[str]) -> int:
        return sum((funcs[n].end_lineno or funcs[n].lineno) - funcs[n].lineno for n in names)

    groups: dict[str, set[str]] = {}
    print(f"{'family':16s} {'funcs':>6s} {'lines':>6s}  status")
    for prefix in prefixes:
        seeds = {n for n in funcs if n.lstrip("_").startswith(prefix) and not _is_command(funcs[n])}
        if not seeds:
            continue
        group = closure(seeds)
        groups[prefix] = group
        external = {d for n in group for d in deps[n] if d not in group and d in top_level}
        status = "CLOSED — extractable as-is" if not external else f"open: needs {sorted(external)}"
        print(f"{prefix:16s} {len(group):6d} {line_count(group):6d}  {status}")

    overlaps = [
        (a, b, len(groups[a] & groups[b]))
        for a, b in itertools.combinations(groups, 2)
        if groups[a] & groups[b]
    ]
    if overlaps:
        print("\nShared closures (these are one cluster, not separate slices):")
        for a, b, count in sorted(overlaps, key=lambda x: -x[2]):
            print(f"  {a} and {b} share {count} functions")

    return 0


DEFAULT_PREFIXES = [
    "workflow",
    "reliability",
    "artifact",
    "gate",
    "doctor",
    "trace",
    "approval",
    "verify",
    "review",
    "commit",
    "objective",
    "config",
    "infra",
    "memory",
    "task",
    "ace",
    "session",
    "instruction",
    "inspect",
    "next",
    "handoff",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", action="append", dest="prefixes")
    parser.add_argument("--path", type=Path, default=CLI_PATH)
    args = parser.parse_args()
    if not args.path.exists():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 2
    return analyse(args.path, args.prefixes or DEFAULT_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
