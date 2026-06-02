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
            "namespace": [namespace],
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
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/write",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.text

    def write_structured(
        self,
        *,
        content: str,
        namespace: str,
        entry_type: str,
        summary: str,
        tags: list[str],
        references: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        agent_id: str = "agentx",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "namespace": namespace,
            "type": entry_type,
            "content": content,
            "summary": summary[:160],
            "tags": tags,
            "references": references or [],
            "metadata": metadata or {},
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/write",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def get(self, entry_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/v1/memory/{entry_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    def link(self, entry_id: str, target_entry_id: str, relation: str = "related") -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/{entry_id}/link",
                headers=self.headers,
                json={"target_entry_id": target_entry_id, "relation": relation},
            )
            response.raise_for_status()
            return response.json()

    def list_entries(
        self,
        namespace: str,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"namespace": namespace, "limit": limit}
        if entry_type:
            params["type"] = entry_type
        if tags:
            params["tags"] = ",".join(tags)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/v1/memory",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("entries", [])
