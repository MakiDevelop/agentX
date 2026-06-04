from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionEntry:
    id: str
    role: str
    content: str
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "ts": self.timestamp,
            "role": self.role,
            "content": self.content,
        }
        if self.parent_id is not None:
            d["parent_id"] = self.parent_id
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    def to_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionEntry:
        return cls(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            parent_id=data.get("parent_id"),
            metadata=data.get("metadata", {}),
            timestamp=data.get("ts", ""),
        )


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._next_seq: int = 0
        self._entries: list[SessionEntry] = []
        if path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in data and "role" in data:
                    entry = SessionEntry.from_dict(data)
                    try:
                        seq = int(entry.id)
                        self._next_seq = max(self._next_seq, seq + 1)
                    except ValueError:
                        self._next_seq = len(self._entries) + 1
                    self._entries.append(entry)

    def _generate_id(self) -> str:
        entry_id = f"{self._next_seq:06d}"
        self._next_seq += 1
        return entry_id

    def append(
        self,
        role: str,
        content: str,
        *,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionEntry:
        entry = SessionEntry(
            id=self._generate_id(),
            role=role,
            content=content,
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    @property
    def entries(self) -> list[SessionEntry]:
        return list(self._entries)

    def replay(self, *, up_to_id: str | None = None) -> list[dict[str, str]]:
        messages = []
        for entry in self._entries:
            messages.append(entry.to_message())
            if up_to_id is not None and entry.id == up_to_id:
                break
        return messages

    @classmethod
    def create(cls, workspace: Path, model: str = "", namespace: str = "") -> SessionStore:
        directory = workspace / ".agentx" / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:6]
        path = directory / f"{stamp}-{uid}.session.jsonl"
        store = cls(path)
        store.append(
            "system",
            f"session_start model={model} namespace={namespace}",
            metadata={"event": "session_start", "model": model, "namespace": namespace},
        )
        return store

    @classmethod
    def load(cls, path: Path) -> SessionStore:
        if not path.exists():
            raise FileNotFoundError(f"Session file not found: {path}")
        return cls(path)


def fork_session(
    source_path: Path,
    from_entry_id: str,
    workspace: Path,
) -> SessionStore:
    source = SessionStore.load(source_path)
    directory = workspace / ".agentx" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:6]
    fork_path = directory / f"{stamp}-{uid}-fork.session.jsonl"

    new_store = SessionStore(fork_path)
    found = False
    for entry in source.entries:
        new_store.append(
            entry.role,
            entry.content,
            metadata={**(entry.metadata or {}), "forked_from": str(source_path)},
        )
        if entry.id == from_entry_id:
            found = True
            break

    if not found:
        raise ValueError(f"Entry ID {from_entry_id!r} not found in {source_path}")

    return new_store
