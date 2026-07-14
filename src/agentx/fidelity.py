from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FidelityCheck:
    id: str
    ok: bool
    detail: str


def run_fidelity_probe(workspace: Path) -> list[FidelityCheck]:
    workspace = workspace.resolve()
    agentyx = _read(workspace / "AGENTX.md")
    bootstrap = _read(workspace / "src" / "agentx" / "bootstrap.py")
    learning = _read(workspace / "src" / "agentx" / "learning.py")
    pre_commit = _read(workspace / ".pre-commit-config.yaml")

    return [
        _check(
            "agentx-md-present",
            agentyx is not None,
            "AGENTX.md must exist as local constitution",
        ),
        _check(
            "mt22-task-truth",
            bool(agentyx and "MT22" in agentyx and "tasks.py" in agentyx and "唯一真相" in agentyx),
            "AGENTX.md must preserve MT22 task truth invariant",
        ),
        _check(
            "no-legacy-task-module",
            not (workspace / "src" / "agentx" / "task.py").exists(),
            "src/agentx/task.py must remain absent",
        ),
        _check(
            "bootstrap-loads-agentx-first",
            bool(
                bootstrap
                and 'LOCAL_INSTRUCTION_FILES = (' in bootstrap
                and 'BootstrapFile("AGENTX.md"' in bootstrap
                and bootstrap.find('BootstrapFile("AGENTX.md"')
                < bootstrap.find('BootstrapFile("AGENTS.md"')
                < bootstrap.find('BootstrapFile("CLAUDE.md"')
            ),
            "bootstrap must load AGENTX.md before AGENTS.md and CLAUDE.md",
        ),
        _check(
            "bootstrap-loads-handoff",
            bool(
                bootstrap
                and 'HANDOFF_FILES = ("NEXT_SESSION.md", "CONVERSATION_HANDOFF.md")' in bootstrap
            ),
            "bootstrap must load NEXT_SESSION and CONVERSATION_HANDOFF",
        ),
        _check(
            "learning-proposal-gate",
            bool(
                learning
                and '"proposed": {"under_review", "approved", "rejected"}' in learning
                and '"approved": {"applied", "rejected"}' in learning
                and 'new_status == "applied" and not applied_to' in learning
            ),
            "learning proposals must pass approval gate before applied",
        ),
        _check(
            "precommit-no-legacy-guard",
            bool(pre_commit and "check-no-legacy-task" in pre_commit),
            "pre-commit must include no-legacy task guard",
        ),
    ]


def format_fidelity_report(checks: list[FidelityCheck]) -> str:
    lines = ["# agentX Fidelity Probe v0"]
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        lines.append(f"- [{status}] {check.id}: {check.detail}")
    return "\n".join(lines)


def fidelity_passed(checks: list[FidelityCheck]) -> bool:
    return all(check.ok for check in checks)


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _check(check_id: str, ok: bool, detail: str) -> FidelityCheck:
    return FidelityCheck(id=check_id, ok=ok, detail=detail)
