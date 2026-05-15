from __future__ import annotations

import tomllib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


from agentx.persona import normalize_persona


CONFIG_KEYS = {"model", "namespace", "mode", "auto_handoff", "approval", "persona"}


@dataclass(frozen=True)
class ProjectConfig:
    model: str | None = None
    namespace: str | None = None
    mode: str | None = None
    auto_handoff: bool | None = None
    approval: str | None = None
    persona: str | None = None


def config_path(workspace: Path) -> Path:
    return workspace / ".agentx" / "config.toml"


def load_project_config(workspace: Path) -> ProjectConfig:
    path = config_path(workspace)
    if not path.exists():
        return ProjectConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    agentx = data.get("agentx", {})
    return ProjectConfig(
        model=agentx.get("model"),
        namespace=agentx.get("namespace"),
        mode=agentx.get("mode"),
        auto_handoff=agentx.get("auto_handoff"),
        approval=agentx.get("approval"),
        persona=agentx.get("persona"),
    )


def set_project_config(workspace: Path, key: str, value: str) -> ProjectConfig:
    if key not in CONFIG_KEYS:
        raise ValueError(f"Unsupported config key: {key}")
    current = load_project_config(workspace)
    data: dict[str, Any] = {
        "model": current.model,
        "namespace": current.namespace,
        "mode": current.mode,
        "auto_handoff": current.auto_handoff,
        "approval": current.approval,
        "persona": current.persona,
    }
    data[key] = _parse_value(key, value)
    updated = ProjectConfig(**data)
    write_project_config(workspace, updated)
    return updated


def write_project_config(workspace: Path, config: ProjectConfig) -> None:
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[agentx]"]
    for key in ("model", "namespace", "mode", "approval", "persona"):
        value = getattr(config, key)
        if value is not None:
            lines.append(f"{key} = {json.dumps(value)}")
    if config.auto_handoff is not None:
        lines.append(f"auto_handoff = {str(config.auto_handoff).lower()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_value(key: str, value: str) -> str | bool:
    value = value.strip()
    if key in {"model", "namespace"}:
        if not value:
            raise ValueError(f"{key} must not be empty")
        return value
    if key == "persona":
        return normalize_persona(value)
    if key == "mode":
        if value not in {"chat", "agent"}:
            raise ValueError("mode must be chat or agent")
        return value
    if key == "approval":
        if value not in {"ask", "auto", "off"}:
            raise ValueError("approval must be ask, auto, or off")
        return value
    if key == "auto_handoff":
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("auto_handoff must be true or false")
    return value
