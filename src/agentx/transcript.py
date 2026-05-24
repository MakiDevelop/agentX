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


def list_transcripts(workspace: Path, limit: int = 10) -> list[Path]:
    directory = workspace / ".agentx" / "sessions"
    if not directory.exists():
        return []
    return sorted(directory.glob("*.jsonl"), reverse=True)[:limit]
