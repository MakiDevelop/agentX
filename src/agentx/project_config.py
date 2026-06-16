from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentx.approval import normalize_approval_mode
from agentx.persona import normalize_persona


CONFIG_KEYS = {"model", "namespace", "mode", "auto_handoff", "approval", "persona", "memory_backend", "memory_amh_store", "memory_amh_path"}


@dataclass(frozen=True)
class ProjectConfig:
    model: str | None = None
    namespace: str | None = None
    mode: str | None = None
    auto_handoff: bool | None = None
    approval: str | None = None
    persona: str | None = None
    memory_backend: str | None = None
    memory_amh_store: str | None = None
    memory_amh_path: str | None = None


def config_path(workspace: Path) -> Path:
    return workspace / ".agentx" / "config.toml"


def load_project_config(workspace: Path) -> ProjectConfig:
    path = config_path(workspace)
    if not path.exists():
        return ProjectConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    agentx = data.get("agentx", {})
    approval = agentx.get("approval")
    if approval is not None:
        approval = normalize_approval_mode(str(approval)).value
    mode = agentx.get("mode")
    if mode is not None:
        mode = str(mode).strip().lower()
    if mode == "ask":
        mode = "agent"
    return ProjectConfig(
        model=agentx.get("model"),
        namespace=agentx.get("namespace"),
        mode=mode,
        auto_handoff=agentx.get("auto_handoff"),
        approval=approval,
        persona=agentx.get("persona"),
        memory_backend=agentx.get("memory_backend"),
        memory_amh_store=agentx.get("memory_amh_store"),
        memory_amh_path=agentx.get("memory_amh_path"),
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
        "memory_backend": current.memory_backend,
        "memory_amh_store": current.memory_amh_store,
        "memory_amh_path": current.memory_amh_path,
    }
    data[key] = _parse_value(key, value)
    updated = ProjectConfig(**data)
    write_project_config(workspace, updated)
    return updated


def write_project_config(workspace: Path, config: ProjectConfig) -> None:
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[agentx]"]
    for key in ("model", "namespace", "mode", "approval", "persona", "memory_backend", "memory_amh_store", "memory_amh_path"):
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
        normalized = value.lower()
        if normalized == "ask":
            return "agent"
        if normalized not in {"chat", "agent"}:
            raise ValueError("mode must be chat, ask, or agent")
        return normalized
    if key == "approval":
        try:
            return normalize_approval_mode(value).value
        except ValueError as exc:
            raise ValueError("approval must be ask, auto, off, strict, auto-approve, or deny") from exc
    if key == "auto_handoff":
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("auto_handoff must be true or false")
    if key == "memory_backend":
        normalized = value.lower().strip()
        if normalized not in {"memhall", "amh"}:
            raise ValueError("memory_backend must be memhall or amh")
        return normalized
    if key == "memory_amh_store":
        normalized = value.lower().strip()
        if normalized not in {"json", "sqlite", "postgres", "memhall"}:
            raise ValueError("memory_amh_store must be one of json, sqlite, postgres, memhall")
        return normalized
    if key == "memory_amh_path":
        if not value.strip():
            raise ValueError("memory_amh_path must not be empty when provided")
        return value.strip()
    return value
