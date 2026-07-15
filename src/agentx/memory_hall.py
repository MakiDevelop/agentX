from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

AMH_STATUS_SCHEMA = "agentx.memory_status.v1"

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
        valid_until: str | None = None,
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
        if valid_until:
            payload["valid_until"] = valid_until

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
        valid_until: str | None = None,
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
        if valid_until:
            payload["valid_until"] = valid_until
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

    # === ACA L2 Trust operations (tier upgrade + audit) ===

    def tier_upgrade(
        self,
        memory_id: str,
        *,
        new_tier: str = "human_confirmed",
        confirmed_by: str,
        method: str = "human_review",
        evidence_ids: list[str] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """
        ACA Tier upgrade (promote llm_derived -> human_confirmed with TrustProof).
        For current memhall backend this writes a structured governance record.
        When switched to full AMH this will map to native tier_upgrade.
        """
        if new_tier not in ACA_SOURCE_TIERS:
            raise ValueError(f"new_tier must be one of {ACA_SOURCE_TIERS}")

        now = datetime.now().isoformat(timespec="seconds") + "Z"
        content = f"Tier upgrade for {memory_id} -> {new_tier} by {confirmed_by}"
        payload = {
            "agent_id": "agentx",
            "namespace": namespace or "project:agentX",
            "type": "tier_upgrade",
            "content": content,
            "summary": f"Upgrade {memory_id} to {new_tier}",
            "tags": ["aca", "tier_upgrade", new_tier],
            "references": [memory_id] + (evidence_ids or []),
            "metadata": {
                "aca_version": "0.1",
                "target_memory_id": memory_id,
                "new_tier": new_tier,
                "trust_proof": {
                    "tier": new_tier,
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now,
                    "evidence_ids": evidence_ids or [],
                    "method": method,
                },
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/memory/write",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def audit(self, memory_id: str) -> list[dict[str, Any]]:
        """
        Return append-only audit events for a memory (ACA L1/L2).
        Current backend best-effort: list related records or return the record itself.
        Full AMH will have dedicated /audit endpoint.
        """
        # Best effort with current memhall: try to get the record + any linked
        try:
            record = self.get(memory_id)
            events = [{"event": "current_record", "data": record}]
            # Also list recent tier_upgrade records referencing it
            upgrades = self.list_entries(
                namespace=record.get("namespace", "project:agentX"),
                entry_type="tier_upgrade",
                limit=20,
            )
            for u in upgrades:
                if memory_id in (u.get("references") or []):
                    events.append({"event": "tier_upgrade", "data": u})
            return events
        except Exception:
            return []


class NullMemoryClient:
    """No-op Memory Hall client for isolated headless runs."""

    base_url = "memory-disabled"
    token = None
    timeout = 0.0
    disabled = True

    @property
    def headers(self) -> dict[str, str]:
        return {}

    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return "[]"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return "memory disabled (--no-memory); write skipped"

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
        valid_until: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "disabled",
            "memory_id": "memory-disabled",
            "output": "memory disabled (--no-memory); ACA write skipped",
            "governance_applied": [{"rule": "memory_disabled"}],
        }

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
        valid_until: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "disabled",
            "memory_id": "memory-disabled",
            "output": "memory disabled (--no-memory); structured write skipped",
        }

    def get(self, entry_id: str) -> dict[str, Any]:
        return {"memory_id": entry_id, "status": "disabled"}

    def link(self, entry_id: str, target_entry_id: str, relation: str = "related") -> dict[str, Any]:
        return {"status": "disabled", "entry_id": entry_id, "target_entry_id": target_entry_id}

    def list_entries(
        self,
        namespace: str,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    def tier_upgrade(
        self,
        memory_id: str,
        *,
        new_tier: str = "human_confirmed",
        confirmed_by: str,
        method: str = "human_review",
        evidence_ids: list[str] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        return {"status": "disabled", "memory_id": memory_id, "new_tier": new_tier}

    def audit(self, memory_id: str) -> list[dict[str, Any]]:
        return []


class AmhClient:
    """
    ACA-conformant client using the official AMH reference implementation
    (npx @chibakuma/agent-memory-hall or global `amh` CLI).
    This makes agentX a proper participant in Agent Civilization Architecture
    when memory_backend=amh.

    Supports common --store values:
      - "json" (default, --store json --path <file>)
      - "sqlite" (--store sqlite --path <file>)
      - "postgres" (--store postgres --path <connstr>)
      - "memhall" (--store memhall --path <url>)

    Uses subprocess to call `amh` (preferred) or full npx command.
    Supports the same interface as MemoryHallClient for drop-in replacement
    in bootstrap, tools, loop, etc.
    """

    def __init__(self, store: str = "json", store_path: str | None = None, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._amh_cmd = self._resolve_amh_cmd()
        self.store = store
        # Support common AMH stores: json, sqlite (need --path file), postgres/memhall (need --path connstr/url)
        # Default path only for file-based stores if not provided
        if store_path is None:
            if store in ("json", "sqlite"):
                ext = "json" if store == "json" else "db"
                self.store_path = str(Path(f".agentx/amh/memory.{ext}").resolve())
            else:
                self.store_path = None
        else:
            self.store_path = store_path
        # Ensure parent dir for file-based stores
        if self.store in ("json", "sqlite") and self.store_path:
            Path(self.store_path).parent.mkdir(parents=True, exist_ok=True)

    def _resolve_amh_cmd(self) -> list[str]:
        if shutil.which("amh"):
            return ["amh"]
        return ["npx", "@chibakuma/agent-memory-hall"]

    def _run_amh(self, *args: str, input_text: str | None = None) -> str:
        cmd = self._amh_cmd + list(args)
        # Always include --store for any supported store (json, sqlite, postgres, memhall, ...)
        cmd += ["--store", self.store]
        if self.store_path:
            cmd += ["--path", self.store_path]
        result = subprocess.run(
            cmd,
            input=input_text.encode() if input_text else None,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"amh command failed: {result.stderr.decode(errors='replace')}")
        return result.stdout.decode(errors="replace")

    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        # AMH CLI read supports ns filter; we do post-filter for query for simplicity
        out = self._run_amh("read", "--ns", namespace, "--limit", str(limit))
        # Simple text filter for query (real AMH would have better search)
        lines = []
        for line in out.splitlines():
            if query.lower() in line.lower():
                lines.append(line)
            if len(lines) >= limit:
                break
        return "\n".join(lines) or out[:2000]

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        # Use ACA-shaped if possible, but CLI accepts text
        entry_type = "handoff" if "handoff" in content.lower() else "note"
        out = self._run_amh(
            "write",
            "--agent", "agentx",
            "--ns", namespace,
            "--type", entry_type,
            content,
        )
        return out.strip()

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
        valid_until: str | None = None,
    ) -> dict[str, Any]:
        # For AMH, we can pass metadata in a structured way via the content or use write with extra
        # For now, embed ACA metadata in the written content as JSON prefix (AMH stores it)
        payload = {
            "content": content,
            "summary": summary,
            "tags": tags,
            "references": references or [],
            "metadata": {"aca": metadata or {}},
        }
        if valid_until:
            payload["valid_until"] = valid_until
        text = json.dumps(payload, ensure_ascii=False)
        out = self._run_amh(
            "write",
            "--agent", agent_id,
            "--ns", namespace,
            "--type", entry_type,
            text,
        )
        # Return synthetic dict
        return {"status": "ok", "output": out.strip(), "memory_id": "amh-cli"}

    def tier_upgrade(
        self,
        memory_id: str,
        *,
        new_tier: str = "human_confirmed",
        confirmed_by: str,
        method: str = "human_review",
        evidence_ids: list[str] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        # Use AMH tier-upgrade if available in newer version, fallback to write
        try:
            out = self._run_amh(
                "tier-upgrade",
                "--id", memory_id,
                "--tier", new_tier,
                "--by", confirmed_by,
            )
            return {"status": "ok", "output": out}
        except Exception:
            # Fallback to writing a governance record
            content = f"Tier upgrade: {memory_id} -> {new_tier} by {confirmed_by} ({method}) evidence={evidence_ids or []}"
            return self.write_structured(
                content=content,
                namespace=namespace or "project:agentX",
                entry_type="tier_upgrade",
                summary=f"Upgrade {memory_id} to {new_tier}",
                tags=["aca", "tier", new_tier],
                metadata={
                    "target_memory_id": memory_id,
                    "new_tier": new_tier,
                    "trust_proof": {
                        "confirmed_by": confirmed_by,
                        "method": method,
                        "evidence_ids": evidence_ids or [],
                    },
                },
            )

    def audit(self, memory_id: str) -> list[dict[str, Any]]:
        # Best effort: read recent records and filter
        out = self._run_amh("read", "--limit", "50")
        events = []
        for line in out.splitlines():
            if memory_id in line:
                events.append({"event": "log", "data": line})
        return events or [{"event": "no_audit", "data": "AMH CLI audit limited; use full AMH for rich logs"}]

    # Minimal compatibility for get / list if needed by existing code
    def get(self, entry_id: str) -> dict[str, Any]:
        return {"memory_id": entry_id, "note": "AMH CLI get is limited"}

    def list_entries(self, namespace: str, entry_type: str | None = None, tags: list[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        out = self._run_amh("read", "--ns", namespace, "--limit", str(limit))
        return [{"content": line} for line in out.splitlines()[:limit]]


def memory_status_payload(
    *,
    workspace: Path,
    namespace: str,
    memory_backend: str,
    memory_amh_store: str | None = None,
    memory_amh_path: str | None = None,
    memory_hall_url: str | None = None,
    memory_hall_token: str | None = None,
    live_probe: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    backend = (memory_backend or "memhall").lower()
    store = memory_amh_store or "json"
    amh_path = memory_amh_path
    if backend == "amh" and amh_path is None and store in {"json", "sqlite"}:
        ext = "json" if store == "json" else "db"
        amh_path = str((workspace / ".agentx" / "amh" / f"memory.{ext}").resolve())

    amh_bin = shutil.which("amh")
    npx_bin = shutil.which("npx")
    amh_command = ["amh"] if amh_bin else ["npx", "@chibakuma/agent-memory-hall"] if npx_bin else []
    amh_available = bool(amh_command)
    live_probe_result: dict[str, Any] | None = None
    warnings: list[str] = []
    blockers: list[str] = []

    if backend == "amh" and not amh_available:
        blockers.append("amh_cli_unavailable")
    if backend not in {"amh", "memhall"}:
        warnings.append("unknown_memory_backend")

    if live_probe and amh_available:
        completed = subprocess.run(
            [*amh_command, "--help"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        live_probe_result = {
            "command": " ".join([*amh_command, "--help"]),
            "exit_code": completed.returncode,
            "ok": completed.returncode == 0,
            "stdout_excerpt": completed.stdout.decode(errors="replace")[:1000],
            "stderr_excerpt": completed.stderr.decode(errors="replace")[:1000],
        }
        if completed.returncode != 0:
            blockers.append("amh_cli_probe_failed")
    elif live_probe and not amh_available:
        live_probe_result = {
            "command": None,
            "exit_code": None,
            "ok": False,
            "stdout_excerpt": "",
            "stderr_excerpt": "amh and npx are unavailable",
        }

    ok = not blockers
    return {
        "schema": AMH_STATUS_SCHEMA,
        "ok": ok,
        "workspace": str(workspace.resolve()),
        "namespace": namespace,
        "memory_backend": backend,
        "live_probe": live_probe,
        "blockers": blockers,
        "warnings": warnings,
        "legacy_memhall": {
            "url": memory_hall_url,
            "token": "set" if memory_hall_token else "missing",
        },
        "amh": {
            "available": amh_available,
            "command": amh_command,
            "binary": amh_bin,
            "npx_binary": npx_bin,
            "using_npx_fallback": not bool(amh_bin) and bool(npx_bin),
            "store": store,
            "path": amh_path,
            "path_exists": bool(Path(amh_path).exists()) if amh_path and store in {"json", "sqlite"} else None,
            "live_probe_result": live_probe_result,
        },
        "recommended_command": "agentx inspect --json"
        if ok
        else "install AMH CLI or set memory_backend=memhall, then rerun agentx memory-status --json",
        "recommended_kind": "inspect" if ok else "fix_memory_status_blockers",
        "recommended_risk": "GREEN" if ok else "UNKNOWN",
        "next_commands": [
            "agentx inspect --json"
            if ok
            else "install AMH CLI or set memory_backend=memhall, then rerun agentx memory-status --json"
        ],
    }
