#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentx.fidelity import fidelity_passed, format_fidelity_report, run_fidelity_probe  # noqa: E402


def main() -> None:
    checks = run_fidelity_probe(ROOT)
    print(format_fidelity_report(checks))
    if not fidelity_passed(checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
