from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx


class MemoryHallClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, headers=self._build_headers())

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @property
    def headers(self) -> dict[str, str]:
        return self._build_headers()

    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        payload: dict[str, Any] = {
            "query": query,
            "namespace": [namespace],
            "mode": "hybrid",
            "limit": limit,
        }
        response = self._client.post(f"{self.base_url}/v1/memory/search", json=payload)
        response.raise_for_status()
        return response.text

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        payload: dict[str, Any] = {
            "agent_id": "agentx",
            "namespace": namespace,
            "type": "handoff" if "handoff" in content.lower() else "note",
            "content": content,
            "summary": content.splitlines()[0][:160] if content else None,
            "tags": ["agentx"],
            "references": [],
            "metadata": {"source": "agentx"},
        }
        response = self._client.post(f"{self.base_url}/v1/memory/write", json=payload)
        response.raise_for_status()
        return response.text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MemoryHallClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
