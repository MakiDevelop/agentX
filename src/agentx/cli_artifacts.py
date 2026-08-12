"""Artifacts, sessions, traces and approval receipts.

The read-only observability surface: what a previous run left behind on disk and
what a runner can learn from it without re-executing anything.

Third slice of `docs/CLI_SPLIT_PLAN.md`, verified closed with
`scripts/find_closed_groups.py` — the transitive closure of these thirty
functions refers to nothing else defined at cli.py's top level.

`parse_headless_payload_text` / `load_headless_payload_file` come along despite
living elsewhere in cli.py: reading an artifact back off disk is what the rest of
this module does, and leaving them behind was the group's only external
dependency.
"""

from __future__ import annotations

import json
import re
import shlex
from collections import Counter
from datetime import datetime
from pathlib import Path

import typer

from agentx.config import Settings
from agentx.tools._helpers import resolve_inside_workspace
from agentx.transcript import (
    approval_receipts,
    find_transcript,
    list_transcripts,
    transcript_overview,
)


def sessions_payload(settings: Settings, *, limit: int = 10) -> dict[str, object]:
    sessions = [
        transcript_overview(path) for path in list_transcripts(settings.workspace, limit=limit)
    ]
    return {
        "schema": "agentx.sessions.v1",
        "workspace": str(settings.workspace),
        "count": len(sessions),
        "sessions": sessions,
    }


def resolve_artifacts_root(workspace: Path, value: str) -> Path:
    try:
        target = resolve_inside_workspace(workspace, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if target.exists() and not (target.is_dir() or target.is_file()):
        raise typer.BadParameter(f"artifacts root is not a directory: {value}")
    return target


def artifact_mtime(path: Path) -> float:
    if path.is_file():
        return path.stat().st_mtime
    candidates = [
        path / "result.json",
        path / "result.jsonl",
        path / "session.session.jsonl",
        path / "handoff.md",
    ]
    existing = [candidate.stat().st_mtime for candidate in candidates if candidate.exists()]
    if existing:
        return max(existing)
    return path.stat().st_mtime


def artifact_mtime_text(path: Path) -> str:
    return datetime.fromtimestamp(artifact_mtime(path)).isoformat(timespec="seconds")


def relative_workspace_path(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def read_artifact_result_payload(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        return load_headless_payload_file(path)
    except (OSError, typer.BadParameter):
        return None


def artifact_handoff_summary(result_payload: dict[str, object] | None) -> dict[str, object]:
    if not result_payload:
        return {}
    log_summary = result_payload.get("log_summary")
    if not isinstance(log_summary, dict):
        return {}
    handoff = log_summary.get("handoff_summary")
    return dict(handoff) if isinstance(handoff, dict) else {}


def artifact_payload_schema(payload: dict[str, object] | None) -> str | None:
    if not payload:
        return None
    value = payload.get("schema") or payload.get("schema_version")
    return str(value) if value else None


def is_workflow_run_artifact_payload(payload: dict[str, object] | None) -> bool:
    return artifact_payload_schema(payload) == "agentx.workflow_run.v1"


def allocate_workflow_resume_auto_result_output(
    workspace: Path,
    *,
    source_name: str,
    resume_output_format: str,
) -> str:
    suffix = "jsonl" if resume_output_format.strip().lower() == "jsonl" else "json"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_name).strip("-_.") or "workflow-run"
    for index in range(1, 1000):
        stem = f"{slug}-next" if index == 1 else f"{slug}-next-{index}"
        relative = Path(".agentx") / "runs" / f"{stem}.{suffix}"
        if not (workspace.resolve() / relative).exists():
            return relative.as_posix()
    raise typer.BadParameter("unable to allocate workflow resume auto result output path")


def artifact_bundle_overview(workspace: Path, bundle: Path) -> dict[str, object]:
    result_json = bundle / "result.json"
    result_jsonl = bundle / "result.jsonl"
    session_path = bundle / "session.session.jsonl"
    handoff_path = bundle / "handoff.md"
    result_path: Path | None = None
    result_format: str | None = None
    result_conflict = result_json.is_file() and result_jsonl.is_file()
    if result_json.is_file():
        result_path = result_json
        result_format = "json"
    elif result_jsonl.is_file():
        result_path = result_jsonl
        result_format = "jsonl"

    result_payload = read_artifact_result_payload(result_path) if result_path else None
    handoff = artifact_handoff_summary(result_payload)
    return {
        "artifact_type": "headless_bundle",
        "name": bundle.name,
        "path": str(bundle),
        "relative_path": relative_workspace_path(workspace, bundle),
        "updated_at": artifact_mtime_text(bundle),
        "has_result": result_path is not None,
        "result_path": str(result_path) if result_path else None,
        "result_relative_path": relative_workspace_path(workspace, result_path)
        if result_path
        else None,
        "result_format": result_format,
        "result_conflict": result_conflict,
        "has_session": session_path.is_file(),
        "session_path": str(session_path) if session_path.is_file() else None,
        "session_relative_path": relative_workspace_path(workspace, session_path)
        if session_path.is_file()
        else None,
        "has_handoff": handoff_path.is_file(),
        "handoff_path": str(handoff_path) if handoff_path.is_file() else None,
        "handoff_relative_path": relative_workspace_path(workspace, handoff_path)
        if handoff_path.is_file()
        else None,
        "schema": artifact_payload_schema(result_payload),
        "schema_version": result_payload.get("schema_version") if result_payload else None,
        "termination": result_payload.get("termination") if result_payload else None,
        "exit_code": result_payload.get("exit_code") if result_payload else None,
        "needs_handoff": bool(handoff.get("needs_handoff", False)),
        "resume_command": handoff.get("resume_command"),
        "workflow_query": None,
        "workflow_ok": None,
        "workflow_execute": None,
        "workflow_stopped_at": None,
        "workflow_blockers": [],
        "workflow_resume_ready": None,
        "workflow_missing_input_count": 0,
        "workflow_next_result_output": None,
        "approval_receipt_count": 0,
    }


def artifact_result_format(path: Path) -> str | None:
    if path.suffix == ".jsonl":
        return "jsonl"
    if path.suffix == ".json":
        return "json"
    return None


def artifact_workflow_run_overview(workspace: Path, path: Path) -> dict[str, object]:
    payload = read_artifact_result_payload(path) or {}
    approval_receipts = payload.get("approval_receipts")
    blockers = payload.get("blockers")
    plan = payload.get("plan")
    plan_inputs = (
        dict(plan.get("inputs") or {})
        if isinstance(plan, dict) and isinstance(plan.get("inputs"), dict)
        else {}
    )
    inputs_required = (
        list(plan.get("inputs_required") or [])
        if isinstance(plan, dict) and isinstance(plan.get("inputs_required"), list)
        else []
    )
    missing_inputs = [
        dict(item)
        for item in inputs_required
        if isinstance(item, dict)
        and str(item.get("placeholder") or "").strip()
        and str(item.get("placeholder") or "").strip() not in plan_inputs
    ]
    workflow_resume_ready = not missing_inputs
    workflow_has_issue = (
        bool(payload.get("stopped_at")) or bool(blockers) or not workflow_resume_ready
    )
    workflow_next_result_output = (
        allocate_workflow_resume_auto_result_output(
            workspace,
            source_name=path.stem,
            resume_output_format="json",
        )
        if not workflow_has_issue
        else None
    )
    return {
        "artifact_type": "workflow_run",
        "name": path.name,
        "path": str(path),
        "relative_path": relative_workspace_path(workspace, path),
        "updated_at": artifact_mtime_text(path),
        "has_result": True,
        "result_path": str(path),
        "result_relative_path": relative_workspace_path(workspace, path),
        "result_format": artifact_result_format(path),
        "result_conflict": False,
        "has_session": False,
        "session_path": None,
        "session_relative_path": None,
        "has_handoff": False,
        "handoff_path": None,
        "handoff_relative_path": None,
        "schema": artifact_payload_schema(payload),
        "schema_version": None,
        "termination": None,
        "exit_code": None,
        "needs_handoff": False,
        "resume_command": None,
        "workflow_query": payload.get("query"),
        "workflow_ok": payload.get("ok"),
        "workflow_execute": payload.get("execute"),
        "workflow_stopped_at": payload.get("stopped_at"),
        "workflow_blockers": list(blockers) if isinstance(blockers, list) else [],
        "workflow_resume_ready": workflow_resume_ready,
        "workflow_missing_input_count": len(missing_inputs),
        "workflow_next_result_output": workflow_next_result_output,
        "approval_receipt_count": len(approval_receipts)
        if isinstance(approval_receipts, list)
        else 0,
    }


def is_artifact_bundle(path: Path) -> bool:
    return any(
        (path / name).is_file()
        for name in ("result.json", "result.jsonl", "session.session.jsonl", "handoff.md")
    )


def is_workflow_run_artifact_file(path: Path) -> bool:
    if not path.is_file() or artifact_result_format(path) is None:
        return False
    return is_workflow_run_artifact_payload(read_artifact_result_payload(path))


def is_artifact_entry(path: Path) -> bool:
    if path.is_dir():
        return is_artifact_bundle(path)
    return is_workflow_run_artifact_file(path)


def artifact_entry_overview(workspace: Path, path: Path) -> dict[str, object]:
    if path.is_file():
        return artifact_workflow_run_overview(workspace, path)
    return artifact_bundle_overview(workspace, path)


def list_artifact_entries(root: Path) -> list[Path]:
    if is_artifact_entry(root):
        return [root]
    if is_artifact_bundle(root):
        return [root]
    if not root.is_dir():
        return []
    return [path for path in root.iterdir() if is_artifact_entry(path)]


def artifacts_payload(
    settings: Settings, *, root: str = ".agentx/runs", limit: int = 20
) -> dict[str, object]:
    artifact_root = resolve_artifacts_root(settings.workspace, root)
    if not artifact_root.exists():
        return {
            "schema": "agentx.artifacts.v1",
            "workspace": str(settings.workspace),
            "root": str(artifact_root),
            "root_relative_path": relative_workspace_path(settings.workspace, artifact_root),
            "ok": True,
            "limit": limit,
            "count": 0,
            "latest_artifact": None,
            "recommended_command": "agentx -p '任務' --agent --artifact-dir .agentx/runs/latest --quiet",
            "recommended_kind": "headless_bundle",
            "recommended_risk": "YELLOW",
            "workflow_chain": None,
            "artifacts": [],
            "detail": f"artifacts root not found: {root}",
        }

    entries = sorted(list_artifact_entries(artifact_root), key=artifact_mtime, reverse=True)[:limit]
    artifacts = [artifact_entry_overview(settings.workspace, entry) for entry in entries]
    latest_artifact = dict(artifacts[0]) if artifacts else None
    recommended_command, recommended_kind, recommended_risk = _artifacts_recommendation(
        latest_artifact
    )
    return {
        "schema": "agentx.artifacts.v1",
        "workspace": str(settings.workspace),
        "root": str(artifact_root),
        "root_relative_path": relative_workspace_path(settings.workspace, artifact_root),
        "ok": True,
        "limit": limit,
        "count": len(artifacts),
        "latest_artifact": latest_artifact,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "workflow_chain": workflow_chain_payload(latest_artifact),
        "artifacts": artifacts,
        "detail": "",
    }


def _artifacts_recommendation(artifact: dict[str, object] | None) -> tuple[str, str, str]:
    if artifact is None:
        return (
            "agentx -p '任務' --agent --artifact-dir .agentx/runs/latest --quiet",
            "headless_bundle",
            "YELLOW",
        )
    artifact_path = str(
        artifact.get("relative_path") or artifact.get("path") or ".agentx/runs/latest"
    )
    if artifact.get("needs_handoff") is True and artifact.get("resume_command"):
        return (
            f"agentx handoff-resume {shlex.quote(artifact_path)} --dry-run",
            "handoff_resume",
            "GREEN",
        )
    return f"agentx artifacts {shlex.quote(artifact_path)} --json", "inspect_artifact", "GREEN"


def workflow_chain_payload(artifact: dict[str, object] | None) -> dict[str, object] | None:
    if artifact is None or artifact.get("artifact_type") != "workflow_run":
        return None
    artifact_path = str(artifact.get("relative_path") or artifact.get("path") or ".agentx/runs")
    blockers = list(artifact.get("workflow_blockers") or [])
    stopped_at = (
        artifact.get("workflow_stopped_at")
        if isinstance(artifact.get("workflow_stopped_at"), dict)
        else None
    )
    resume_ready = artifact.get("workflow_resume_ready") is True
    missing_input_count = int(artifact.get("workflow_missing_input_count", 0) or 0)
    has_issue = bool(stopped_at) or bool(blockers) or not resume_ready
    next_result_output = str(artifact.get("workflow_next_result_output") or "") or None
    recommended_command = (
        f"agentx workflow-inspect {shlex.quote(artifact_path)} --json"
        if has_issue
        else f"agentx workflow-resume {shlex.quote(artifact_path)} --result-output auto --dry-run --json"
    )
    return {
        "status": "needs_inspect" if has_issue else "ready",
        "latest_artifact": artifact_path,
        "latest_query": artifact.get("workflow_query"),
        "latest_ok": artifact.get("workflow_ok"),
        "latest_stopped": stopped_at,
        "blocker_count": len(blockers),
        "missing_input_count": missing_input_count,
        "resume_ready": resume_ready,
        "next_result_output": None if has_issue else next_result_output,
        "recommended_command": recommended_command,
        "recommended_kind": "workflow_artifact_inspect" if has_issue else "workflow_resume",
    }


def approvals_payload(
    settings: Settings,
    *,
    session: str = "latest",
    limit: int = 20,
    denied_only: bool = False,
) -> dict[str, object]:
    """Return approval receipts from a saved transcript for headless audit."""
    path = find_transcript(settings.workspace, session)
    if path is None:
        return {
            "schema": "agentx.approvals.v1",
            "workspace": str(settings.workspace),
            "session": session,
            "ok": False,
            "path": None,
            "denied_only": denied_only,
            "limit": limit,
            "count": 0,
            "denied_count": 0,
            "receipts": [],
            "detail": f"transcript not found: {session}",
        }

    receipts = approval_receipts(path, limit=limit, denied_only=denied_only)
    denied_count = sum(1 for receipt in receipts if receipt.get("allowed") is False)
    return {
        "schema": "agentx.approvals.v1",
        "workspace": str(settings.workspace),
        "session": session,
        "ok": True,
        "path": str(path),
        "denied_only": denied_only,
        "limit": limit,
        "count": len(receipts),
        "denied_count": denied_count,
        "receipts": receipts,
        "detail": "",
    }


def read_transcript_records(path: Path) -> tuple[list[dict[str, object]], int]:
    records: list[dict[str, object]] = []
    invalid_line_count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_line_count += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                invalid_line_count += 1
    return records, invalid_line_count


def trace_event_name(record: dict[str, object]) -> str:
    event = record.get("event")
    if event:
        return str(event)
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata.get("event"):
        return str(metadata["event"])
    role = record.get("role")
    if role:
        return f"role:{role}"
    return "record"


def transcript_event_excerpt(record: dict[str, object]) -> dict[str, object]:
    excerpt: dict[str, object] = {
        "ts": record.get("ts"),
        "event": trace_event_name(record),
    }
    for key in ("mode", "command", "tool", "action", "ok", "allowed", "risk", "source", "reason"):
        if key in record:
            excerpt[key] = record.get(key)
    text = record.get("content") or record.get("result") or record.get("summary")
    if text is not None:
        excerpt["text"] = str(text).replace("\n", " ")[:240]
    return excerpt


def trace_tool_name(record: dict[str, object]) -> str | None:
    if trace_event_name(record) != "tool":
        return None
    for key in ("tool", "command", "action"):
        value = record.get(key)
        if value:
            return str(value)
    return "(unknown)"


def traces_payload(
    settings: Settings,
    *,
    session: str = "latest",
    limit: int = 20,
) -> dict[str, object]:
    path = find_transcript(settings.workspace, session)
    if path is None:
        return {
            "schema": "agentx.traces.v1",
            "workspace": str(settings.workspace),
            "session": session,
            "ok": False,
            "path": None,
            "limit": limit,
            "count": 0,
            "invalid_line_count": 0,
            "event_counts": {},
            "tool_counts": {},
            "approval_count": 0,
            "approval_denied_count": 0,
            "tool_failure_count": 0,
            "error_like_count": 0,
            "first_ts": None,
            "last_ts": None,
            "recent_events": [],
            "detail": f"transcript not found: {session}",
        }

    records, invalid_line_count = read_transcript_records(path)
    event_counts = Counter(trace_event_name(record) for record in records)
    tool_counts = Counter(
        tool_name for record in records if (tool_name := trace_tool_name(record)) is not None
    )
    approval_count = int(event_counts.get("approval", 0))
    approval_denied_count = sum(
        1
        for record in records
        if trace_event_name(record) == "approval" and record.get("allowed") is False
    )
    tool_failure_count = sum(
        1 for record in records if trace_event_name(record) == "tool" and record.get("ok") is False
    )
    error_like_count = sum(
        1
        for record in records
        if "error" in trace_event_name(record).lower()
        or record.get("ok") is False
        or record.get("allowed") is False
    )
    timestamps = [str(record.get("ts")) for record in records if record.get("ts")]
    return {
        "schema": "agentx.traces.v1",
        "workspace": str(settings.workspace),
        "session": session,
        "ok": True,
        "path": str(path),
        "limit": limit,
        "count": len(records),
        "invalid_line_count": invalid_line_count,
        "event_counts": dict(sorted(event_counts.items())),
        "tool_counts": dict(sorted(tool_counts.items())),
        "approval_count": approval_count,
        "approval_denied_count": approval_denied_count,
        "tool_failure_count": tool_failure_count,
        "error_like_count": error_like_count,
        "first_ts": timestamps[0] if timestamps else None,
        "last_ts": timestamps[-1] if timestamps else None,
        "recent_events": [transcript_event_excerpt(record) for record in records[-limit:]],
        "detail": "",
    }


def approvals_exit_code(payload: dict[str, object], *, fail_on_denied: bool = False) -> int:
    if not fail_on_denied:
        return 0
    return 1 if int(payload.get("denied_count", 0)) > 0 else 0


def parse_headless_payload_text(text: str) -> dict[str, object]:
    text = text.strip()
    if not text:
        raise typer.BadParameter("payload file is empty")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
        if parsed is None:
            raise typer.BadParameter("payload file must contain JSON or JSONL objects") from None

    if not isinstance(parsed, dict):
        raise typer.BadParameter("payload root must be a JSON object")
    data = parsed.get("data") if parsed.get("event") else parsed
    if not isinstance(data, dict):
        raise typer.BadParameter("payload data must be a JSON object")
    return data


def load_headless_payload_file(path: Path) -> dict[str, object]:
    return parse_headless_payload_text(path.read_text(encoding="utf-8"))
