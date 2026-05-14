from __future__ import annotations

from pathlib import Path

from agentx.bootstrap import build_repo_context


def build_project_profile(workspace: Path, namespace: str) -> str:
    files = {path.name for path in workspace.iterdir()}
    detected = []
    if "pyproject.toml" in files:
        detected.append("Python project")
    if "package.json" in files:
        detected.append("Node project")
    if "uv.lock" in files:
        detected.append("uv-managed dependencies")

    test_commands = []
    if "pyproject.toml" in files:
        test_commands.extend(["uv run ruff check .", "uv run pytest -q"])
    if "package.json" in files:
        test_commands.append("npm test")

    return (
        "agentX project profile\n"
        f"namespace: {namespace}\n"
        f"workspace: {workspace}\n"
        f"detected: {', '.join(detected) if detected else 'unknown'}\n"
        f"test commands: {', '.join(test_commands) if test_commands else 'unknown'}\n\n"
        f"{build_repo_context(workspace, max_chars=8000)}"
    )
