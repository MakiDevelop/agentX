from __future__ import annotations

from typing import Any

import httpx


class MemoryHallClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        payload: dict[str, Any] = {
            "query": query,
            "namespace": namespace,
            "mode": "hybrid",
            "limit": limit,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/search",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.text

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        payload = {"content": content, "namespace": namespace}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/write",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.text

