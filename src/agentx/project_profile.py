from __future__ import annotations

from pathlib import Path

from agentx.bootstrap import build_repo_context


def build_project_profile_payload(workspace: Path, namespace: str) -> dict[str, object]:
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

    repo_context = build_repo_context(workspace, max_chars=8000)
    return {
        "schema": "agentx.project_profile.v1",
        "namespace": namespace,
        "workspace": str(workspace),
        "detected": detected,
        "test_commands": test_commands,
        "repo_context": repo_context,
    }


def build_project_profile(workspace: Path, namespace: str) -> str:
    payload = build_project_profile_payload(workspace, namespace)
    return (
        "agentX project profile\n"
        f"namespace: {payload['namespace']}\n"
        f"workspace: {payload['workspace']}\n"
        f"detected: {', '.join(payload['detected']) if payload['detected'] else 'unknown'}\n"
        f"test commands: {', '.join(payload['test_commands']) if payload['test_commands'] else 'unknown'}\n\n"
        f"{payload['repo_context']}"
    )
