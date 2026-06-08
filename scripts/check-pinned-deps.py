#!/usr/bin/env python3
"""Check that all direct dependencies in pyproject.toml use exact pins.

Port/adaptation of earendil-works/pi 's check-pinned-deps.mjs (layer 1 of 4
supply-chain hardening).

Rules (adapted for Python/uv):
- Direct runtime and optional dependencies must be pinned with exact version
  (==X.Y.Z). Loose specifiers (>=, ~=, <, >, !=, *, etc.) are forbidden for
  direct deps.
- URL / git / path / VCS references are allowed (they are not "registry" loose
  versions) but should be reviewed.
- Transitive deps are locked by uv.lock (see check-lockfile-commit and
  `uv lock --check`).
- This script is intentionally small and has no third-party runtime deps.

Exit non-zero on any violation (for CI / pre-commit).

Usage:
    python scripts/check-pinned-deps.py
    uv run python scripts/check-pinned-deps.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path("pyproject.toml")

# Operators that indicate a non-exact / range dependency.
LOOSE_OPS_RE = re.compile(r"[<>!~]|(?<![=])=(?![=])|\*")

# Matches things that are clearly not PyPI version specifiers (VCS, local, etc.).
NON_REGISTRY_PREFIXES = (
    "git+",
    "https://",
    "http://",
    "file:",
    "path:",
    "ssh:",
    "hg+",
    "svn+",
    "bzr+",
)


def is_non_registry_specifier(spec: str) -> bool:
    s = spec.strip().lower()
    if any(s.startswith(p) for p in NON_REGISTRY_PREFIXES):
        return True
    # "name @ git+..." or "name @ https://..."
    if " @" in spec and any(x in s for x in ("git+", "http", "file:", "path:")):
        return True
    return False


def is_exact_pinned_version_spec(version_part: str) -> bool:
    """Return True only for simple exact pins like '==1.2.3' or '==1.2.3+local'.

    Rejects any range, compatible release, wildcard, compound specifiers,
    and the triple-equals form (===) that some tools accept but we treat as
    non-standard for our "exact pin" rule.
    """
    v = version_part.strip()
    if not v:
        return False
    if "," in v:
        return False
    if LOOSE_OPS_RE.search(v):
        return False
    # Must be exactly one == (not ===) followed by a concrete version token.
    if not re.match(r"^==\s*[0-9v][\w.+-]*$", v):
        return False
    return True


def parse_requirement_string(req: str) -> tuple[str, str] | None:
    """Return (name, version_spec_part) or None if unparsable / not a versioned req."""
    # Split off environment marker first.
    req = req.split(";", 1)[0].strip()
    if not req or req.startswith("#"):
        return None

    # Common forms:
    # name
    # name[extra]
    # name>=1.0
    # name[extra]>=1.0
    # name @ url...
    # name[extra] @ url...
    m = re.match(
        r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?\s*(.*)$",
        req,
    )
    if not m:
        return None

    name = m.group(1)
    version_part = m.group(3).strip()

    # If it was a bare name with no version at all, version_part == "".
    return name, version_part


def check_pyproject() -> list[str]:
    if not PYPROJECT.exists():
        print("pyproject.toml not found", file=sys.stderr)
        sys.exit(2)

    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    failures: list[str] = []

    sections: list[tuple[str, list[str]]] = []

    # Runtime deps
    runtime = project.get("dependencies", [])
    if runtime:
        sections.append(("project.dependencies", runtime))

    # Optional / extras
    for extra, deps in project.get("optional-dependencies", {}).items():
        sections.append((f"project.optional-dependencies.{extra}", deps))

    for section_name, deps in sections:
        for raw in deps:
            if not isinstance(raw, str):
                continue
            if is_non_registry_specifier(raw):
                continue  # git / url / path — caller responsibility to review

            parsed = parse_requirement_string(raw)
            if not parsed:
                continue
            _name, version_part = parsed

            if not is_exact_pinned_version_spec(version_part):
                failures.append(f"{PYPROJECT}:{section_name}  {raw!r}  (must be exact ==pin)")

    return failures


def main() -> None:
    failures = check_pyproject()

    if failures:
        print("Direct dependencies must use exact version pins (==X.Y.Z):", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nFix: edit the specifier in pyproject.toml to an exact pin, then\n"
            "uv lock  (and review the resulting uv.lock diff).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("All direct dependencies are exactly pinned.")


if __name__ == "__main__":
    main()
