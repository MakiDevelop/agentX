from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentx.persona import normalize_persona
from agentx.project_config import load_project_config

DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_BACKEND = "ollama"  # "ollama" or "llamacpp"


@dataclass(frozen=True)
class Settings:
    model: str
    backend: str
    ollama_url: str
    llamacpp_url: str
    ollama_timeout: float
    memory_hall_url: str
    memory_hall_token: str | None
    max_steps: int
    context_limit_tokens: int
    auto_handoff: bool
    persona: str
    workspace: Path

    def __init__(self) -> None:
        workspace = Path(os.getenv("AGENTX_WORKSPACE", os.getcwd())).resolve()
        config = load_project_config(workspace)
        auto_handoff = config.auto_handoff if config.auto_handoff is not None else True
        if "AGENTX_AUTO_HANDOFF" in os.environ:
            auto_handoff = os.getenv("AGENTX_AUTO_HANDOFF") != "0"
        self._set_values(
            model=os.getenv("AGENTX_MODEL") or config.model or DEFAULT_MODEL,
            backend=os.getenv("AGENTX_BACKEND", DEFAULT_BACKEND),
            ollama_url=os.getenv("AGENTX_OLLAMA_URL", "http://127.0.0.1:11434"),
            llamacpp_url=os.getenv("AGENTX_LLAMACPP_URL", "http://127.0.0.1:8080"),
            ollama_timeout=float(os.getenv("AGENTX_OLLAMA_TIMEOUT", "60")),
            memory_hall_url=os.getenv("AGENTX_MEMORY_HALL_URL", "http://100.122.171.74:9100"),
            memory_hall_token=os.getenv("AGENTX_MEMORY_HALL_TOKEN") or os.getenv("MH_API_TOKEN"),
            max_steps=int(os.getenv("AGENTX_MAX_STEPS", "8")),
            context_limit_tokens=int(os.getenv("AGENTX_CONTEXT_LIMIT", "8192")),
            auto_handoff=auto_handoff,
            persona=normalize_persona(os.getenv("AGENTX_PERSONA") or config.persona or "default"),
            workspace=workspace,
        )

    @classmethod
    def from_values(
        cls,
        *,
        model: str,
        backend: str,
        ollama_url: str,
        llamacpp_url: str,
        ollama_timeout: float,
        memory_hall_url: str,
        memory_hall_token: str | None,
        max_steps: int,
        context_limit_tokens: int,
        auto_handoff: bool,
        persona: str,
        workspace: Path,
    ) -> "Settings":
        settings = cls.__new__(cls)
        settings._set_values(
            model=model,
            backend=backend,
            ollama_url=ollama_url,
            llamacpp_url=llamacpp_url,
            ollama_timeout=ollama_timeout,
            memory_hall_url=memory_hall_url,
            memory_hall_token=memory_hall_token,
            max_steps=max_steps,
            context_limit_tokens=context_limit_tokens,
            auto_handoff=auto_handoff,
            persona=persona,
            workspace=workspace,
        )
        return settings

    def with_updates(self, **changes: object) -> "Settings":
        values = {
            "model": self.model,
            "backend": self.backend,
            "ollama_url": self.ollama_url,
            "llamacpp_url": self.llamacpp_url,
            "ollama_timeout": self.ollama_timeout,
            "memory_hall_url": self.memory_hall_url,
            "memory_hall_token": self.memory_hall_token,
            "max_steps": self.max_steps,
            "context_limit_tokens": self.context_limit_tokens,
            "auto_handoff": self.auto_handoff,
            "persona": self.persona,
            "workspace": self.workspace,
        }
        values.update(changes)
        return type(self).from_values(**values)

    def _set_values(
        self,
        *,
        model: str,
        backend: str,
        ollama_url: str,
        llamacpp_url: str,
        ollama_timeout: float,
        memory_hall_url: str,
        memory_hall_token: str | None,
        max_steps: int,
        context_limit_tokens: int,
        auto_handoff: bool,
        persona: str,
        workspace: Path,
    ) -> None:
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "ollama_url", ollama_url)
        object.__setattr__(self, "llamacpp_url", llamacpp_url)
        object.__setattr__(self, "ollama_timeout", ollama_timeout)
        object.__setattr__(self, "memory_hall_url", memory_hall_url)
        object.__setattr__(self, "memory_hall_token", memory_hall_token)
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(self, "context_limit_tokens", context_limit_tokens)
        object.__setattr__(self, "auto_handoff", auto_handoff)
        object.__setattr__(self, "persona", persona)
        object.__setattr__(self, "workspace", workspace)
