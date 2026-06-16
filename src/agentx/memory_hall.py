from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

# === ACA (Agent Civilization Architecture) constants ===
# See docs from agent-memory-hall: Agent_Civilization_Architecture.md + Anti_Ouroboros_Evidence.md
# agentX aims for L1 (Memory) + L2 (Trust) conformance when writing organizational memory.

ACA_SOURCE_TIERS = ("raw_source", "llm_derived", "human_confirmed")
ACA_MEMORY_TYPES = ("decision", "fact", "preference", "constraint", "lesson", "risk", "handoff", "note")

# Anti-Ouroboros rule (L2 Trust invariant):
# LLM-derived knowledge MUST NOT supersede LLM-derived knowledge without human intervention.


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

    def _compute_content_hash(self, content: str) -> str:
        # BLAKE3 preferred in ACA spec; fall back to sha256 for now (compatible hash)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        """Legacy write. For ACA conformance prefer write_aca or write_structured with tier."""
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

    def write_aca(
        self,
        *,
        content: str,
        namespace: str,
        memory_type: str = "note",
        source_tier: str = "llm_derived",
        agent_id: str = "agentx",
        summary: str | None = None,
        tags: list[str] | None = None,
        references: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """
        ACA-conformant write (L1 Memory + L2 Trust).
        - Enforces source_tier from ACA_SOURCE_TIERS.
        - Records content_hash for future dedup/audit.
        - Embeds source.tier + aca_version for interoperability with AMH / Agent Civilization Architecture.
        - Client-side Anti-Ouroboros guard: llm_derived should not blindly supersede llm_derived.
          (Full gate belongs in AMH backend; here we surface the signal.)
        """
        if source_tier not in ACA_SOURCE_TIERS:
            raise ValueError(f"source_tier must be one of {ACA_SOURCE_TIERS}, got {source_tier}")
        if memory_type not in ACA_MEMORY_TYPES:
            # Fail closed (per ACA spirit + Codex Low feedback)
            raise ValueError(f"memory_type must be one of {ACA_MEMORY_TYPES}, got {memory_type}")

        now = datetime.now().isoformat(timespec="seconds") + "Z"
        content_hash = self._compute_content_hash(content)
        summary = (summary or (content.splitlines()[0][:160] if content else ""))[:160]

        source_type = "agent" if "agent" in (agent_id or "") else "human"
        source_ref = f"agentx:{datetime.now().strftime('%Y-%m-%d')}"

        aca_metadata = {
            "aca_version": "0.1",
            # Flat keys for AMH memhall adapter compatibility (Codex Medium fix)
            "source_type": source_type,
            "source_ref": source_ref,
            "source_tier": source_tier,
            # Rich nested form for full ACA consumers
            "source": {
                "type": source_type,
                "ref": source_ref,
                "tier": source_tier,
            },
            "content_hash": content_hash,
            "hash_algorithm": "sha256",  # explicit; AMH native prefers BLAKE3
            "created_at": now,
            "created_by": created_by or agent_id,
            **(metadata or {}),
        }

        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "namespace": namespace,
            "type": memory_type,
            "content": content,
            "summary": summary,
            "tags": tags or ["agentx", f"tier:{source_tier}"],
            "references": references or [],
            "metadata": aca_metadata,
        }

        # Simple client-side Anti-Ouroboros signal (best-effort).
        # In real ACA/AMH the TierGate lives in the server.
        if source_tier == "llm_derived":
            # We do not block here (to preserve existing flows), but we annotate.
            # Future: query recent and attach "anti_ouroboros_check": "llm_derived_chain" if needed.
            payload["metadata"]["anti_ouroboros"] = "llm_derived_write"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/write",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            data.setdefault("governance_applied", []).append({"rule": "aca_tier", "tier": source_tier})
            return data

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
        """Backward-compatible structured write. New code should prefer write_aca for ACA records."""
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
