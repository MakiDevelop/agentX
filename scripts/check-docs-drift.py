#!/usr/bin/env python3
"""Fail when the docs claim something the code does not implement.

This repo has now been bitten by hand-maintained duplicates of machine-readable
truth three separate times:

  - `safety.py` carried a risk table no production code consulted; 6 of 33 tools
    had drifted, and `write_file` was listed RED while really being YELLOW.
  - The system prompt's tool list had drifted from the ToolRegistry: 11 tools
    were never taught to the model, and the prose referenced a tool the list did
    not define.
  - README documented 46 of the 51 CLI commands.

Each was found by hand. This script turns that into a check, because the fix for
"someone forgot to update the docs" is not "remember harder".

Checks:
  1. Every `agentx <command>` in the CLI appears in README.md.
  2. README does not document commands that do not exist.

Run: uv run python scripts/check-docs-drift.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

#: Commands intentionally not documented in README (with a reason, always).
UNDOCUMENTED_ALLOWLIST: dict[str, str] = {}


def cli_commands() -> list[str]:
    """Ask Click for the command list — do not parse `--help` output.

    An earlier version scraped `agentx --help`. That broke in CI: the runner
    wrapped the help table differently, so the line regex matched words out of
    command *descriptions* and reported phantom commands like "agentx or" and
    "agentx plus". Parsing human-formatted output is the exact failure mode this
    script exists to prevent, so it now reads the Typer app directly.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from typer.main import get_command

    from agentx.cli import app

    command = get_command(app)
    commands = getattr(command, "commands", None)
    if not commands:
        return []
    return sorted(commands)


def main() -> int:
    commands = cli_commands()
    if not commands:
        print("could not enumerate CLI commands from `agentx --help`", file=sys.stderr)
        return 2

    readme = README.read_text(encoding="utf-8")
    documented = set(re.findall(r"agentx ([a-z][a-z0-9-]*)", readme))

    missing = [c for c in commands if c not in documented and c not in UNDOCUMENTED_ALLOWLIST]
    phantom = sorted(documented - set(commands))

    problems = False
    if missing:
        problems = True
        print(f"README does not document {len(missing)} CLI command(s):", file=sys.stderr)
        for name in missing:
            print(f"  - agentx {name}", file=sys.stderr)
        print(file=sys.stderr)
        print("Document them, or add to UNDOCUMENTED_ALLOWLIST with a reason.", file=sys.stderr)

    if phantom:
        print(f"\nREADME documents {len(phantom)} command(s) that do not exist:", file=sys.stderr)
        for name in phantom:
            print(f"  - agentx {name}", file=sys.stderr)
        problems = True

    if problems:
        return 1

    print(f"docs in sync: all {len(commands)} CLI commands documented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
