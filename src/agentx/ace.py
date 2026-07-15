from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


ACE_SCHEMA = "agentx.ace_session.v1"
DEFAULT_ACE_ROOT = Path.home() / "Documents" / "agent-council"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def validate_ace_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id_required")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("session_id_must_not_contain_path_separators")
    if not SESSION_ID_RE.fullmatch(normalized):
        raise ValueError("session_id_contains_unsupported_characters")
    return normalized


def resolve_ace_root(root: str | Path | None = None) -> Path:
    return Path(root).expanduser().resolve() if root is not None else DEFAULT_ACE_ROOT


def ace_session_paths(session_id: str, *, root: str | Path | None = None) -> tuple[Path, Path]:
    normalized = validate_ace_session_id(session_id)
    root_path = resolve_ace_root(root)
    session_dir = (root_path / normalized).resolve()
    if root_path != session_dir and root_path not in session_dir.parents:
        raise ValueError("session_dir_escapes_root")
    return session_dir, session_dir / "_manifest.md"


def render_ace_manifest(
    *,
    session_id: str,
    goal: str,
    routing_decision: str = "",
    created_by: str = "agentx",
    created_at: str | None = None,
) -> str:
    timestamp = created_at or datetime.now().isoformat(timespec="seconds")
    route = routing_decision.strip() or "Not assigned yet."
    return "\n".join(
        [
            f"# ACE Session: {session_id}",
            "",
            f"- Created: {timestamp}",
            f"- Created by: {created_by}",
            "",
            "## GOAL",
            "",
            goal.strip() or "TBD",
            "",
            "## ROUTING DECISIONS",
            "",
            route,
            "",
            "## SUB-TASKS",
            "",
            "- No sub-tasks recorded yet.",
            "",
            "## CUMULATIVE FINDINGS",
            "",
            "- No findings recorded yet.",
            "",
            "## DECISIONS TAKEN",
            "",
            "- No decisions recorded yet.",
            "",
            "## OPEN QUESTIONS",
            "",
            "- No open questions recorded yet.",
            "",
        ]
    )


def ace_init_payload(
    *,
    session_id: str,
    goal: str,
    routing_decision: str = "",
    root: str | Path | None = None,
    write: bool = False,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    session_dir: Path | None = None
    manifest_path: Path | None = None

    try:
        normalized_id = validate_ace_session_id(session_id)
        session_dir, manifest_path = ace_session_paths(normalized_id, root=root)
    except ValueError as exc:
        normalized_id = session_id.strip()
        blockers.append(str(exc))

    if not goal.strip():
        blockers.append("goal_required")

    manifest = ""
    if not blockers:
        manifest = render_ace_manifest(
            session_id=normalized_id,
            goal=goal,
            routing_decision=routing_decision,
        )
        if write and manifest_path is not None and session_dir is not None:
            if manifest_path.exists():
                blockers.append("manifest_already_exists")
            else:
                session_dir.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(manifest, encoding="utf-8")
        elif not write:
            warnings.append("dry_run_no_files_written")

    ok = not blockers
    return {
        "schema": ACE_SCHEMA,
        "ok": ok,
        "write": write,
        "session_id": normalized_id,
        "root": str(resolve_ace_root(root)),
        "session_dir": str(session_dir) if session_dir else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "manifest_exists": bool(manifest_path.exists()) if manifest_path else False,
        "blockers": blockers,
        "warnings": warnings,
        "manifest": manifest,
        "recommended_command": f"agentx ace-init {normalized_id} --goal GOAL --write --json"
        if ok and not write
        else "agentx next --json"
        if ok
        else "fix ACE blockers, then rerun agentx ace-init SESSION --goal GOAL --json",
        "recommended_kind": "ace_init_write" if ok and not write else "next" if ok else "fix_ace_blockers",
        "recommended_risk": "YELLOW" if ok and not write else "GREEN" if ok else "UNKNOWN",
        "next_commands": [
            f"agentx ace-init {normalized_id} --goal GOAL --write --json"
            if ok and not write
            else "agentx next --json"
            if ok
            else "fix ACE blockers, then rerun agentx ace-init SESSION --goal GOAL --json"
        ],
    }
