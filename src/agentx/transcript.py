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
