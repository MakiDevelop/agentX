from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentx.persona import normalize_persona
from agentx.project_config import load_project_config

DEFAULT_MODEL = "gemma4:31b"


@dataclass(frozen=True)
class Settings:
    model: str
    ollama_url: str
    ollama_timeout: float
    memory_hall_url: str
    memory_hall_token: str | None
    memory_backend: str
    memory_amh_store: str
    memory_amh_path: str | None
    max_steps: int
    context_limit_tokens: int
    auto_handoff: bool
    persona: str
    workspace: Path
    learning_enabled: bool = True

    def __init__(self) -> None:
        workspace = Path(os.getenv("AGENTX_WORKSPACE", os.getcwd())).resolve()
        config = load_project_config(workspace)
        auto_handoff = config.auto_handoff if config.auto_handoff is not None else True
        if "AGENTX_AUTO_HANDOFF" in os.environ:
            auto_handoff = os.getenv("AGENTX_AUTO_HANDOFF") != "0"
        self._set_values(
            model=os.getenv("AGENTX_MODEL") or config.model or DEFAULT_MODEL,
            ollama_url=os.getenv("AGENTX_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_timeout=float(os.getenv("AGENTX_OLLAMA_TIMEOUT", "60")),
            memory_hall_url=os.getenv("AGENTX_MEMORY_HALL_URL", "http://100.122.171.74:9100"),
            memory_hall_token=os.getenv("AGENTX_MEMORY_HALL_TOKEN") or os.getenv("MH_API_TOKEN"),
            memory_backend=os.getenv("AGENTX_MEMORY_BACKEND") or config.memory_backend or "memhall",
            memory_amh_store=config.memory_amh_store or os.getenv("AGENTX_AMH_STORE") or "json",
            memory_amh_path=config.memory_amh_path or os.getenv("AGENTX_AMH_PATH"),
            max_steps=int(os.getenv("AGENTX_MAX_STEPS", "8")),
            context_limit_tokens=int(os.getenv("AGENTX_CONTEXT_LIMIT", "32768")),
            auto_handoff=auto_handoff,
            persona=normalize_persona(os.getenv("AGENTX_PERSONA") or config.persona or "default"),
            workspace=workspace,
            learning_enabled=os.getenv("AGENTX_LEARNING", "1") != "0",
        )

    @classmethod
    def from_values(
        cls,
        *,
        model: str,
        ollama_url: str,
        ollama_timeout: float,
        memory_hall_url: str,
        memory_hall_token: str | None,
        memory_backend: str,
        memory_amh_store: str,
        memory_amh_path: str | None,
        max_steps: int,
        context_limit_tokens: int,
        auto_handoff: bool,
        persona: str,
        workspace: Path,
        learning_enabled: bool = True,
    ) -> "Settings":
        settings = cls.__new__(cls)
        settings._set_values(
            model=model,
            ollama_url=ollama_url,
            ollama_timeout=ollama_timeout,
            memory_hall_url=memory_hall_url,
            memory_hall_token=memory_hall_token,
            memory_backend=memory_backend,
            memory_amh_store=memory_amh_store,
            memory_amh_path=memory_amh_path,
            max_steps=max_steps,
            context_limit_tokens=context_limit_tokens,
            auto_handoff=auto_handoff,
            persona=persona,
            workspace=workspace,
            learning_enabled=learning_enabled,
        )
        return settings

    def with_updates(self, **changes: object) -> "Settings":
        values = {
            "model": self.model,
            "ollama_url": self.ollama_url,
            "ollama_timeout": self.ollama_timeout,
            "memory_hall_url": self.memory_hall_url,
            "memory_hall_token": self.memory_hall_token,
            "memory_backend": self.memory_backend,
            "memory_amh_store": self.memory_amh_store,
            "memory_amh_path": self.memory_amh_path,
            "max_steps": self.max_steps,
            "context_limit_tokens": self.context_limit_tokens,
            "auto_handoff": self.auto_handoff,
            "persona": self.persona,
            "workspace": self.workspace,
            "learning_enabled": self.learning_enabled,
        }
        values.update(changes)
        return type(self).from_values(**values)

    def _set_values(
        self,
        *,
        model: str,
        ollama_url: str,
        ollama_timeout: float,
        memory_hall_url: str,
        memory_hall_token: str | None,
        memory_backend: str,
        memory_amh_store: str,
        memory_amh_path: str | None,
        max_steps: int,
        context_limit_tokens: int,
        auto_handoff: bool,
        persona: str,
        workspace: Path,
        learning_enabled: bool = True,
    ) -> None:
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "ollama_url", ollama_url)
        object.__setattr__(self, "ollama_timeout", ollama_timeout)
        object.__setattr__(self, "memory_hall_url", memory_hall_url)
        object.__setattr__(self, "memory_hall_token", memory_hall_token)
        object.__setattr__(self, "memory_backend", memory_backend)
        object.__setattr__(self, "memory_amh_store", memory_amh_store)
        object.__setattr__(self, "memory_amh_path", memory_amh_path)
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(self, "context_limit_tokens", context_limit_tokens)
        object.__setattr__(self, "auto_handoff", auto_handoff)
        object.__setattr__(self, "persona", persona)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "learning_enabled", learning_enabled)
