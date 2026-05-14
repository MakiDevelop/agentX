from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("AGENTX_MODEL", "gemma3:latest")
    ollama_url: str = os.getenv("AGENTX_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_timeout: float = float(os.getenv("AGENTX_OLLAMA_TIMEOUT", "60"))
    memory_hall_url: str = os.getenv("AGENTX_MEMORY_HALL_URL", "http://100.122.171.74:9100")
    memory_hall_token: str | None = os.getenv("AGENTX_MEMORY_HALL_TOKEN")
    max_steps: int = int(os.getenv("AGENTX_MAX_STEPS", "8"))
    workspace: Path = Path(os.getenv("AGENTX_WORKSPACE", os.getcwd())).resolve()
