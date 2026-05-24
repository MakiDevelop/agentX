from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def state_path(workspace: Path) -> Path:
    return workspace / ".agentx" / "state.json"


def load_state(workspace: Path) -> dict[str, Any]:
    path = state_path(workspace)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(workspace: Path, state: dict[str, Any]) -> None:
    path = state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_show_guide_hint(workspace: Path) -> bool:
    return not bool(load_state(workspace).get("guide_hint_seen"))


def mark_guide_hint_seen(workspace: Path) -> None:
    state = load_state(workspace)
    state["guide_hint_seen"] = True
    save_state(workspace, state)
