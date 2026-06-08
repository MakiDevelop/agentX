#!/usr/bin/env python3
"""Pre-commit / CI guard that makes uv.lock changes "reviewed code".

Direct port/adaptation of earendil-works/pi 's check-lockfile-commit.mjs
(one of the four supply-chain hardening layers).

Behavior:
- If uv.lock is NOT staged → exit 0 (nothing to do).
- If AGENTX_ALLOW_LOCKFILE_CHANGE=1|true|yes → allow (with note).
- Otherwise → print review checklist + summary of changes (if detectable),
  tell the committer to use the env var *only if* the change was intentional
  and reviewed, then exit 1.

This forces every direct or transitive lockfile change to be a deliberate,
reviewed action (matching pi's "Treat npm dep and lockfile changes as reviewed code").

Intended to be wired via .pre-commit-config.yaml (local hook) and also runnable
manually before `git commit`.

The script never auto-stages or modifies anything.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LOCKFILE = "uv.lock"
ALLOW_ENV = "AGENTX_ALLOW_LOCKFILE_CHANGE"


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            encoding="utf8",
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        return e.output or ""


def is_lockfile_staged() -> bool:
    staged = run_git(["diff", "--cached", "--name-only"]).splitlines()
    return LOCKFILE in (s.strip() for s in staged if s.strip())


def get_allow_flag() -> bool:
    val = os.environ.get(ALLOW_ENV, "").lower()
    return val in ("1", "true", "yes", "on")


def get_staged_lock_diff() -> str:
    # A compact unified diff focused on package name/version hunks.
    try:
        return run_git(["diff", "--cached", "-U0", "--", LOCKFILE])
    except Exception:
        return ""


def summarize_changes(diff: str, max_lines: int = 30) -> list[str]:
    """Very lightweight summary: look for +/- lines that declare package names."""
    summary: list[str] = []
    for line in diff.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        # Common in uv.lock: name = "foo"  or version = "1.2.3" near it.
        if 'name = "' in line or "name='" in line:
            # Extract a bit of context.
            name = line.split("name = ")[-1].strip().strip("\"'")
            summary.append(f"{'+' if line.startswith('+') else '-'} {name}")
        if len(summary) >= max_lines:
            break
    return summary


def main() -> None:
    if not Path(LOCKFILE).exists():
        # Nothing to guard if the project does not (yet) use uv.lock.
        sys.exit(0)

    if not is_lockfile_staged():
        sys.exit(0)

    if get_allow_flag():
        print(
            f"{LOCKFILE} is staged; {ALLOW_ENV} is set, allowing commit.",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"{LOCKFILE} is staged.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Review lockfile changes before committing:", file=sys.stderr)
    print("  - confirm every new/updated package (direct + transitive) is intentional", file=sys.stderr)
    print("  - confirm you are not pulling in brand-new same-day releases (age gate)", file=sys.stderr)
    print("  - review any new packages that may execute code at build/install time", file=sys.stderr)
    print("  - run: python scripts/check-pinned-deps.py  &&  uv lock --check", file=sys.stderr)
    print("  - consider running a vulnerability audit (pip-audit / uvx pip-audit)", file=sys.stderr)
    print("  - if this affects published artifacts later, plan constraints / export update", file=sys.stderr)
    print("", file=sys.stderr)

    diff = get_staged_lock_diff()
    summary = summarize_changes(diff)
    if summary:
        print("Detected package-level changes (best effort):", file=sys.stderr)
        for item in summary:
            print(f"  {item}", file=sys.stderr)
        if len(summary) >= 30:
            print("  ... (truncated)", file=sys.stderr)
    else:
        print("Run this for a full human-readable diff:", file=sys.stderr)
        print(f"  git diff --cached -- {LOCKFILE} | less", file=sys.stderr)

    print("", file=sys.stderr)
    print("If the lockfile change is intentional AND reviewed, commit with:", file=sys.stderr)
    print(f"  {ALLOW_ENV}=1 git commit ...", file=sys.stderr)
    print("", file=sys.stderr)
    print("Never bypass just to make the commit green.", file=sys.stderr)

    sys.exit(1)


if __name__ == "__main__":
    main()
