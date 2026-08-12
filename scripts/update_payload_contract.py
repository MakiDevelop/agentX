#!/usr/bin/env python3
"""Regenerate the runner payload contract snapshot.

    uv run python scripts/update_payload_contract.py

Run this only when a payload change is *intended*, and commit the result
alongside the change so the contract movement is visible in review.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_runner_payload_contract import (  # noqa: E402
    CONTRACT_COMMANDS,
    SNAPSHOT_PATH,
    _run,
    _shape,
)


def main() -> int:
    workspace = Path(tempfile.mkdtemp())
    (workspace / "README.md").write_text("# fixture\n", encoding="utf-8")

    snapshot = {
        name: _shape(_run(args, workspace, takes_workspace))
        for name, args, takes_workspace in CONTRACT_COMMANDS
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)} ({len(snapshot)} commands)")
    for name, shape in snapshot.items():
        print(f"  {name:14s} {len(shape)} top-level keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
