from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TaskState:
    title: str = ""
    status: str = "none"
    created_at: str = ""
    updated_at: str = ""

    @property
    def active(self) -> bool:
        return bool(self.title) and self.status == "active"


def task_path(workspace: Path) -> Path:
    return workspace / ".agentx" / "task.json"


def load_task(workspace: Path) -> TaskState:
    path = task_path(workspace)
    if not path.exists():
        return TaskState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return TaskState()
    return TaskState(**{key: data.get(key, "") for key in TaskState.__dataclass_fields__})


def save_task(workspace: Path, task: TaskState) -> None:
    path = task_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(task), ensure_ascii=False, indent=2), encoding="utf-8")


def start_task(workspace: Path, title: str) -> TaskState:
    now = datetime.now().isoformat(timespec="seconds")
    task = TaskState(title=title, status="active", created_at=now, updated_at=now)
    save_task(workspace, task)
    return task


def finish_task(workspace: Path) -> TaskState:
    task = load_task(workspace)
    task.status = "done"
    task.updated_at = datetime.now().isoformat(timespec="seconds")
    save_task(workspace, task)
    return task


def clear_task(workspace: Path) -> TaskState:
    task = TaskState()
    path = task_path(workspace)
    if path.exists():
        path.unlink()
    return task
