#!/usr/bin/env python3
"""Static guard against reintroducing the removed MT22 legacy task module."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


DEFAULT_ROOT = Path("src")
LEGACY_MODULE = "agentx.task"


def find_legacy_task_violations(root: Path = DEFAULT_ROOT) -> list[str]:
    violations: list[str] = []
    package_root = root / "agentx"
    legacy_file = package_root / "task.py"
    if legacy_file.exists():
        violations.append(f"{legacy_file}: legacy module file must not exist")

    for path in sorted(root.rglob("*.py")):
        if any(part == "__pycache__" for part in path.parts):
            continue
        violations.extend(_legacy_import_violations(path, package_root))

    return violations


def _legacy_import_violations(path: Path, package_root: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: cannot parse Python file: {exc.msg}"]

    violations: list[str] = []
    in_agentx_package = package_root in path.parents or path.parent == package_root
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == LEGACY_MODULE or alias.name.startswith(f"{LEGACY_MODULE}."):
                    violations.append(f"{path}:{node.lineno}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == LEGACY_MODULE or module.startswith(f"{LEGACY_MODULE}."):
                violations.append(f"{path}:{node.lineno}: forbidden import from {module}")
            elif module == "agentx" and any(alias.name == "task" for alias in node.names):
                violations.append(f"{path}:{node.lineno}: forbidden import from agentx.task")
            elif in_agentx_package and node.level == 1 and module == "task":
                violations.append(f"{path}:{node.lineno}: forbidden relative import from .task")

    return violations


def main() -> None:
    violations = find_legacy_task_violations()
    if not violations:
        print("No legacy agentx.task imports found.")
        return

    print("Legacy task module guard failed:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Use agentx.tasks instead. src/agentx/task.py was removed in MT22.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
