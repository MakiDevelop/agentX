from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


ACE_SCHEMA = "agentx.ace_session.v1"
ACE_APPEND_SCHEMA = "agentx.ace_append.v1"
ACE_BRIEFING_SCHEMA = "agentx.ace_briefing.v1"
ACE_ANSWER_SCHEMA = "agentx.ace_answer.v1"
ACE_STATUS_SCHEMA = "agentx.ace_status.v1"
DEFAULT_ACE_ROOT = Path.home() / "Documents" / "agent-council"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
AGENT_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
ACE_APPEND_SECTIONS = {
    "routing": "ROUTING DECISIONS",
    "sub-task": "SUB-TASKS",
    "subtask": "SUB-TASKS",
    "finding": "CUMULATIVE FINDINGS",
    "decision": "DECISIONS TAKEN",
    "question": "OPEN QUESTIONS",
}
ACE_MANIFEST_SECTIONS = [
    "GOAL",
    "ROUTING DECISIONS",
    "SUB-TASKS",
    "CUMULATIVE FINDINGS",
    "DECISIONS TAKEN",
    "OPEN QUESTIONS",
]
ACE_PLACEHOLDER_BULLETS = {
    "- No sub-tasks recorded yet.",
    "- No findings recorded yet.",
    "- No decisions recorded yet.",
    "- No open questions recorded yet.",
}


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


def validate_ace_agent_slug(agent: str) -> str:
    normalized = agent.strip()
    if not normalized:
        raise ValueError("agent_required")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("agent_must_not_contain_path_separators")
    if not AGENT_SLUG_RE.fullmatch(normalized):
        raise ValueError("agent_contains_unsupported_characters")
    return normalized


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


def resolve_ace_append_section(section: str) -> tuple[str, str]:
    raw = section.strip().lower()
    if not raw:
        raise ValueError("section_required")
    heading = ACE_APPEND_SECTIONS.get(raw)
    if heading is None:
        raise ValueError("unknown_section")
    return raw, heading


def format_ace_append_entry(section: str, text: str, *, agent: str = "agentx") -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        raise ValueError("text_required")
    return f"- {timestamp} [{agent}] {cleaned}"


def append_to_manifest_section(content: str, heading: str, entry: str) -> str:
    marker = f"## {heading}"
    lines = content.splitlines()
    try:
        index = next(i for i, line in enumerate(lines) if line.strip() == marker)
    except StopIteration as exc:
        raise ValueError("manifest_section_missing") from exc

    insert_at = index + 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, entry)
    return "\n".join(lines).rstrip() + "\n"


def extract_manifest_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_heading = ""
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current_heading = heading if heading in ACE_MANIFEST_SECTIONS else ""
            if current_heading:
                sections.setdefault(current_heading, [])
            continue
        if current_heading:
            sections[current_heading].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def manifest_section_bullets(section_text: str) -> list[str]:
    bullets = []
    for line in section_text.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("- ") and cleaned not in ACE_PLACEHOLDER_BULLETS:
            bullets.append(cleaned)
    return bullets


def ace_session_file_info(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def cap_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars < 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def ace_append_payload(
    *,
    session_id: str,
    section: str,
    text: str,
    root: str | Path | None = None,
    agent: str = "agentx",
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    session_dir: Path | None = None
    manifest_path: Path | None = None
    entry = ""
    raw_section = section.strip().lower()
    heading = ""

    try:
        normalized_id = validate_ace_session_id(session_id)
        session_dir, manifest_path = ace_session_paths(normalized_id, root=root)
    except ValueError as exc:
        normalized_id = session_id.strip()
        blockers.append(str(exc))

    try:
        raw_section, heading = resolve_ace_append_section(section)
    except ValueError as exc:
        blockers.append(str(exc))

    try:
        entry = format_ace_append_entry(section, text, agent=agent)
    except ValueError as exc:
        blockers.append(str(exc))

    before = ""
    after = ""
    if manifest_path is not None:
        if not manifest_path.exists():
            blockers.append("manifest_not_found")
        elif not blockers:
            before = manifest_path.read_text(encoding="utf-8")
            try:
                after = append_to_manifest_section(before, heading, entry)
            except ValueError as exc:
                blockers.append(str(exc))
            else:
                manifest_path.write_text(after, encoding="utf-8")
    ok = not blockers
    return {
        "schema": ACE_APPEND_SCHEMA,
        "ok": ok,
        "session_id": normalized_id,
        "root": str(resolve_ace_root(root)),
        "session_dir": str(session_dir) if session_dir else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "section": raw_section,
        "heading": heading,
        "entry": entry,
        "manifest_exists": bool(manifest_path.exists()) if manifest_path else False,
        "blockers": blockers,
        "warnings": warnings,
        "manifest": after if ok else before,
        "recommended_command": "agentx next --json"
        if ok
        else "fix ACE append blockers, then rerun agentx ace-append SESSION SECTION TEXT --json",
        "recommended_kind": "next" if ok else "fix_ace_append_blockers",
        "recommended_risk": "GREEN" if ok else "UNKNOWN",
        "next_commands": [
            "agentx next --json"
            if ok
            else "fix ACE append blockers, then rerun agentx ace-append SESSION SECTION TEXT --json"
        ],
    }


def render_ace_briefing(
    *,
    session_id: str,
    agent: str,
    role: str,
    task: str,
    manifest: str,
    constraints: str = "",
) -> str:
    return "\n".join(
        [
            f"# ACE Briefing: {agent}",
            "",
            f"- Session: {session_id}",
            f"- Role: {role.strip() or 'Contributor'}",
            "",
            "## Task",
            "",
            task.strip() or "Read the manifest and propose the next concrete contribution.",
            "",
            "## Constraints",
            "",
            constraints.strip() or "- Treat `_manifest.md` as the shared in-flight state.",
            "- Do not overwrite other agents' raw answers; append new findings instead.",
            "- Return blockers, dissent, and confidence explicitly.",
            "",
            "## Manifest Snapshot",
            "",
            manifest.strip(),
            "",
        ]
    )


def ace_briefing_payload(
    *,
    session_id: str,
    agent: str,
    role: str = "Contributor",
    task: str = "",
    constraints: str = "",
    root: str | Path | None = None,
    output: str | None = None,
    write: bool = False,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    session_dir: Path | None = None
    manifest_path: Path | None = None
    briefing_path: Path | None = None
    manifest = ""
    briefing = ""

    try:
        normalized_id = validate_ace_session_id(session_id)
        session_dir, manifest_path = ace_session_paths(normalized_id, root=root)
    except ValueError as exc:
        normalized_id = session_id.strip()
        blockers.append(str(exc))

    try:
        agent_slug = validate_ace_agent_slug(agent)
    except ValueError as exc:
        agent_slug = agent.strip()
        blockers.append(str(exc))

    if manifest_path is not None:
        if not manifest_path.exists():
            blockers.append("manifest_not_found")
        else:
            manifest = manifest_path.read_text(encoding="utf-8")

    if session_dir is not None and not blockers:
        output_name = output.strip() if output else f"briefing-{agent_slug}.md"
        if "/" in output_name or "\\" in output_name or output_name in {"", ".", ".."}:
            blockers.append("output_must_be_session_relative_filename")
        else:
            briefing_path = (session_dir / output_name).resolve()
            if session_dir != briefing_path.parent:
                blockers.append("output_escapes_session_dir")

    if not blockers:
        briefing = render_ace_briefing(
            session_id=normalized_id,
            agent=agent_slug,
            role=role,
            task=task,
            constraints=constraints,
            manifest=manifest,
        )
        if write:
            if briefing_path is None:
                blockers.append("briefing_path_unresolved")
            elif briefing_path.exists():
                blockers.append("briefing_already_exists")
            else:
                briefing_path.write_text(briefing, encoding="utf-8")
        else:
            warnings.append("dry_run_no_files_written")

    ok = not blockers
    return {
        "schema": ACE_BRIEFING_SCHEMA,
        "ok": ok,
        "write": write,
        "session_id": normalized_id,
        "agent": agent_slug,
        "role": role,
        "root": str(resolve_ace_root(root)),
        "session_dir": str(session_dir) if session_dir else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "briefing_path": str(briefing_path) if briefing_path else None,
        "briefing_exists": bool(briefing_path.exists()) if briefing_path else False,
        "blockers": blockers,
        "warnings": warnings,
        "briefing": briefing,
        "recommended_command": f"agentx ace-briefing {normalized_id} --agent {agent_slug} --write --json"
        if ok and not write
        else "agentx next --json"
        if ok
        else "fix ACE briefing blockers, then rerun agentx ace-briefing SESSION --agent AGENT --json",
        "recommended_kind": "ace_briefing_write" if ok and not write else "next" if ok else "fix_ace_briefing_blockers",
        "recommended_risk": "YELLOW" if ok and not write else "GREEN" if ok else "UNKNOWN",
        "next_commands": [
            f"agentx ace-briefing {normalized_id} --agent {agent_slug} --write --json"
            if ok and not write
            else "agentx next --json"
            if ok
            else "fix ACE briefing blockers, then rerun agentx ace-briefing SESSION --agent AGENT --json"
        ],
    }


def render_ace_answer(
    *,
    session_id: str,
    agent: str,
    summary: str,
    answer: str,
) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    return "\n".join(
        [
            f"# ACE Answer: {agent}",
            "",
            f"- Session: {session_id}",
            f"- Agent: {agent}",
            f"- Created: {timestamp}",
            "",
            "## Summary",
            "",
            summary.strip() or "No summary provided.",
            "",
            "## Raw Answer",
            "",
            answer.strip(),
            "",
        ]
    )


def ace_answer_payload(
    *,
    session_id: str,
    agent: str,
    answer: str,
    summary: str = "",
    section: str = "finding",
    root: str | Path | None = None,
    output: str | None = None,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    session_dir: Path | None = None
    manifest_path: Path | None = None
    answer_path: Path | None = None
    answer_doc = ""
    manifest = ""
    entry = ""
    raw_section = section.strip().lower()
    heading = ""

    try:
        normalized_id = validate_ace_session_id(session_id)
        session_dir, manifest_path = ace_session_paths(normalized_id, root=root)
    except ValueError as exc:
        normalized_id = session_id.strip()
        blockers.append(str(exc))

    try:
        agent_slug = validate_ace_agent_slug(agent)
    except ValueError as exc:
        agent_slug = agent.strip()
        blockers.append(str(exc))

    try:
        raw_section, heading = resolve_ace_append_section(section)
    except ValueError as exc:
        blockers.append(str(exc))

    if not answer.strip():
        blockers.append("answer_required")

    if manifest_path is not None:
        if not manifest_path.exists():
            blockers.append("manifest_not_found")
        else:
            manifest = manifest_path.read_text(encoding="utf-8")

    if session_dir is not None and not blockers:
        timestamp_slug = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_name = output.strip() if output else f"answer-{agent_slug}-{timestamp_slug}.md"
        if "/" in output_name or "\\" in output_name or output_name in {"", ".", ".."}:
            blockers.append("output_must_be_session_relative_filename")
        else:
            answer_path = (session_dir / output_name).resolve()
            if session_dir != answer_path.parent:
                blockers.append("output_escapes_session_dir")

    if not blockers:
        summary_text = summary.strip() or answer.strip().splitlines()[0][:160]
        answer_doc = render_ace_answer(
            session_id=normalized_id,
            agent=agent_slug,
            summary=summary_text,
            answer=answer,
        )
        if answer_path is None:
            blockers.append("answer_path_unresolved")
        elif answer_path.exists():
            blockers.append("answer_already_exists")
        else:
            entry = format_ace_append_entry(
                section,
                f"{agent_slug} answer: {summary_text} (answer: {answer_path.name})",
                agent=agent_slug,
            )
            try:
                updated_manifest = append_to_manifest_section(manifest, heading, entry)
            except ValueError as exc:
                blockers.append(str(exc))
            else:
                answer_path.write_text(answer_doc, encoding="utf-8")
                if manifest_path is not None:
                    manifest_path.write_text(updated_manifest, encoding="utf-8")
                manifest = updated_manifest

    ok = not blockers
    return {
        "schema": ACE_ANSWER_SCHEMA,
        "ok": ok,
        "session_id": normalized_id,
        "agent": agent_slug,
        "root": str(resolve_ace_root(root)),
        "session_dir": str(session_dir) if session_dir else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "answer_path": str(answer_path) if answer_path else None,
        "answer_exists": bool(answer_path.exists()) if answer_path else False,
        "section": raw_section,
        "heading": heading,
        "entry": entry,
        "blockers": blockers,
        "warnings": warnings,
        "answer_document": answer_doc,
        "manifest": manifest if ok else "",
        "recommended_command": "agentx next --json"
        if ok
        else "fix ACE answer blockers, then rerun agentx ace-answer SESSION --agent AGENT --answer TEXT --json",
        "recommended_kind": "next" if ok else "fix_ace_answer_blockers",
        "recommended_risk": "GREEN" if ok else "UNKNOWN",
        "next_commands": [
            "agentx next --json"
            if ok
            else "fix ACE answer blockers, then rerun agentx ace-answer SESSION --agent AGENT --answer TEXT --json"
        ],
    }


def ace_status_payload(
    *,
    session_id: str,
    root: str | Path | None = None,
    max_manifest_chars: int = 12000,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []
    session_dir: Path | None = None
    manifest_path: Path | None = None
    manifest = ""
    sections: dict[str, str] = {}
    section_entries: dict[str, list[str]] = {}
    briefings: list[dict[str, object]] = []
    answers: list[dict[str, object]] = []

    try:
        normalized_id = validate_ace_session_id(session_id)
        session_dir, manifest_path = ace_session_paths(normalized_id, root=root)
    except ValueError as exc:
        normalized_id = session_id.strip()
        blockers.append(str(exc))

    if manifest_path is not None:
        if not manifest_path.exists():
            blockers.append("manifest_not_found")
        else:
            manifest = manifest_path.read_text(encoding="utf-8")

    if session_dir is not None and not blockers:
        briefings = [ace_session_file_info(path) for path in sorted(session_dir.glob("briefing-*.md")) if path.is_file()]
        answers = [ace_session_file_info(path) for path in sorted(session_dir.glob("answer-*.md")) if path.is_file()]
        sections = extract_manifest_sections(manifest)
        section_entries = {heading: manifest_section_bullets(text) for heading, text in sections.items()}
        missing_sections = [heading for heading in ACE_MANIFEST_SECTIONS if heading not in sections]
        if missing_sections:
            warnings.append("manifest_sections_missing:" + ",".join(missing_sections))

    manifest_excerpt, manifest_truncated = cap_text(manifest, max_manifest_chars)
    open_questions = section_entries.get("OPEN QUESTIONS", [])
    ok = not blockers
    recommended_command = (
        f"agentx ace-briefing {normalized_id} --agent AGENT --json"
        if ok and open_questions
        else "agentx next --json"
        if ok
        else "fix ACE status blockers, then rerun agentx ace-status SESSION --json"
    )
    return {
        "schema": ACE_STATUS_SCHEMA,
        "ok": ok,
        "session_id": normalized_id,
        "root": str(resolve_ace_root(root)),
        "session_dir": str(session_dir) if session_dir else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "manifest_exists": bool(manifest_path.exists()) if manifest_path else False,
        "blockers": blockers,
        "warnings": warnings,
        "sections": sections,
        "section_entries": section_entries,
        "open_questions": open_questions,
        "briefings": briefings,
        "answers": answers,
        "counts": {
            "briefings": len(briefings),
            "answers": len(answers),
            "open_questions": len(open_questions),
            "section_entries": {heading: len(entries) for heading, entries in section_entries.items()},
        },
        "manifest": manifest_excerpt,
        "manifest_truncated": manifest_truncated,
        "recommended_command": recommended_command,
        "recommended_kind": "ace_briefing" if ok and open_questions else "next" if ok else "fix_ace_status_blockers",
        "recommended_risk": "GREEN" if ok else "UNKNOWN",
        "next_commands": [recommended_command],
    }
