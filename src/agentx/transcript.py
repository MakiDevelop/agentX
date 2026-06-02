from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class Transcript:
    def __init__(self, workspace: Path, model: str, namespace: str) -> None:
        self.path = self._new_path(workspace)
        self.model = model
        self.namespace = namespace
        self.write("session_start", {"model": model, "namespace": namespace})

    def write(self, event: str, data: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _new_path(workspace: Path) -> Path:
        directory = workspace / ".agentx" / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return directory / f"{stamp}.jsonl"


def find_transcript(
    workspace: Path,
    name: str = "latest",
    *,
    exclude: Path | None = None,
) -> Path | None:
    directory = workspace / ".agentx" / "sessions"
    if not directory.exists():
        return None
    excluded = exclude.resolve() if exclude is not None else None
    if name == "latest":
        candidates = [
            path
            for path in sorted(directory.glob("*.jsonl"))
            if excluded is None or path.resolve() != excluded
        ]
        return candidates[-1] if candidates else None

    direct = (directory / name).resolve()
    if direct.is_file() and directory.resolve() in direct.parents and direct != excluded:
        return direct

    with_suffix = (directory / f"{name}.jsonl").resolve()
    if with_suffix.is_file() and directory.resolve() in with_suffix.parents and with_suffix != excluded:
        return with_suffix
    return None


def summarize_transcript(path: Path, limit: int = 12) -> str:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") in {"user", "assistant", "tool", "handoff"}:
                records.append(record)

    lines = [f"Resumed transcript: {path}"]
    for record in records[-limit:]:
        event = record.get("event", "unknown")
        content = str(record.get("content") or record.get("result") or record.get("command") or "")
        mode = record.get("mode")
        prefix = f"{event}({mode})" if mode else event
        lines.append(f"- {prefix}: {content.replace(chr(10), ' ')[:500]}")
    return "\n".join(lines)


def resume_loaded_message(path: Path, summary: str) -> str:
    """Return a concise user-facing confirmation for /resume."""
    lines = [line for line in summary.splitlines() if line.strip()]
    token_estimate = len(summary) // 4
    return (
        f"resumed {path.stem}\n"
        f"source: {path}\n"
        f"loaded summary: {len(lines)} lines, ~{token_estimate} tokens\n"
        "next: continue your prompt, or use /context to inspect usage"
    )


def transcript_overview(path: Path) -> dict[str, str | int]:
    """Return compact metadata for a transcript list view."""
    started = path.stem
    model = ""
    namespace = ""
    turns = 0
    last_event = ""
    last_text = ""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = str(record.get("event", ""))
            if event == "session_start":
                model = str(record.get("model", ""))
                namespace = str(record.get("namespace", ""))
                started = str(record.get("ts", started))
            if event in {"user", "assistant"}:
                turns += 1
                last_event = event
                last_text = str(record.get("content", "")).replace("\n", " ")[:120]
            elif event in {"handoff", "resume", "compact"}:
                last_event = event
                last_text = str(record.get("result") or record.get("summary") or "").replace("\n", " ")[:120]
    return {
        "name": path.stem,
        "started": started,
        "model": model or "-",
        "namespace": namespace or "-",
        "turns": turns,
        "last": f"{last_event}: {last_text}" if last_event else "-",
        "path": str(path),
    }


def list_transcripts(workspace: Path, limit: int = 10) -> list[Path]:
    directory = workspace / ".agentx" / "sessions"
    if not directory.exists():
        return []
    return sorted(directory.glob("*.jsonl"), reverse=True)[:limit]
