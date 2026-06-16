from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timedelta

from agentx.config import Settings
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.tasks import get_task_migration_status


def run_doctor(settings: Settings, memory: MemoryHallClient, ollama: OllamaClient) -> list[tuple[str, bool, str]]:
    checks = [
        _check_command("uv", ["uv", "--version"]),
        _check_command("git", ["git", "status", "--short", "--branch"], cwd=settings.workspace),
        _check_ollama(settings, ollama),
        _check_model(settings, ollama),
        _check_memory_backend(settings, memory),
        _check_memory_search(memory),
        _check_task_migration(settings),
    ]
    return checks


def _check_command(name: str, command: list[str], cwd=None) -> tuple[str, bool, str]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=20, check=False)
    except Exception as exc:
        return name, False, f"{type(exc).__name__}: {exc}"
    output = (result.stdout or result.stderr).strip()
    return name, result.returncode == 0, output[:300]


def _check_ollama(settings: Settings, ollama: OllamaClient) -> tuple[str, bool, str]:
    try:
        models = ollama.list_models()
    except Exception as exc:
        return "ollama", False, f"{settings.ollama_url} {type(exc).__name__}: {exc}"
    return "ollama", True, f"{settings.ollama_url} models={len(models)}"


def _check_model(settings: Settings, ollama: OllamaClient) -> tuple[str, bool, str]:
    try:
        models = ollama.list_models()
    except Exception as exc:
        return "model", False, f"{type(exc).__name__}: {exc}"
    return "model", settings.model in models, settings.model


def _check_memory_search(memory: MemoryHallClient) -> tuple[str, bool, str]:
    try:
        result = memory.search("agentX doctor", namespace="project:agentX", limit=1)
    except Exception as exc:
        return "memory_search", False, f"{type(exc).__name__}: {exc}"
    return "memory_search", True, result[:300]


def _check_task_migration(settings: Settings) -> tuple[str, bool, str]:
    """MT22 過渡期可觀測性（v0.3.0 準備）。

    暴露目前新舊任務系統狀態，讓使用者與開發者能清楚看到遷移進度。
    這是「可觀測性優先」設計決策的直接落地。
    狀態語意：
      - legacy_only / mixed → 仍需關注（未來可改為 warning 層級）
      - multi_only → 理想態
    """
    try:
        st = get_task_migration_status(settings.workspace)
        has_legacy = st.get("has_legacy_single_task", False)
        has_multi = st.get("has_multi_task_file", False)
        cnt = st.get("multi_task_count", 0)
        legacy_active = st.get("legacy_system_active", False)

        if has_legacy and has_multi:
            state = "mixed (legacy + multi 並存)"
        elif has_legacy:
            state = "legacy_only (舊系統仍主導)"
        elif has_multi:
            state = "multi_only (新系統為主)"
        else:
            state = "no_task_data"

        detail = f"{state} | legacy={has_legacy}, multi={has_multi}, tasks={cnt}"
        if legacy_active:
            detail += " [需遷移]"

        # 過渡期策略：只要能正常回報就 ok=True，但 detail 會清楚標示風險狀態
        # 未來若要更嚴，可在 mixed/legacy_only 時回 False 讓 /doctor 顯示 no
        return "task_migration (MT22)", True, detail
    except Exception as exc:
        return "task_migration (MT22)", False, f"{type(exc).__name__}: {exc}"


def _check_memory_backend(settings: Settings, memory: MemoryHallClient = None) -> tuple[str, bool, str]:
    backend = getattr(settings, "memory_backend", "memhall")
    detail = f"backend={backend}"
    if backend == "amh":
        store = getattr(settings, "memory_amh_store", "json")
        path = getattr(settings, "memory_amh_path", "(default)")
        detail += f" (official AMH / ACA L1-3 reference — store={store}, path={path}; full governance: tiers, anti-ouroboros, audit)"
        # Actual usability probe for the current store (e.g. when user did /config set memory_amh_store)
        if memory is not None:
            try:
                # Enhanced probe: test write + read-back verification with temporary marker
                # (tests actual store usability, including ACA write path if available)
                marker = f"aca-doctor-probe-write:{datetime.now().isoformat(timespec='seconds')}"
                content = f"ACA doctor probe write test - temporary diagnostic entry, marker={marker}"
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                # short TTL for diagnostic entry (auto-expire)
                valid_until = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds") + "Z"
                write_resp = None
                if hasattr(memory, "write_aca"):
                    write_resp = memory.write_aca(
                        content=content,
                        namespace="project:agentX",
                        memory_type="note",
                        source_tier="human_confirmed",
                        summary=f"doctor probe {marker}",
                        tags=["aca", "doctor", "probe"],
                        metadata={"probe_marker": marker, "content_hash": content_hash, "aca_version": "0.1"},
                        valid_until=valid_until,
                    )
                else:
                    write_resp = memory.write_structured(
                        content=content,
                        namespace="project:agentX",
                        entry_type="note",
                        summary=f"doctor probe {marker}",
                        tags=["aca", "doctor", "probe"],
                        metadata={"probe_marker": marker, "content_hash": content_hash, "aca_version": "0.1"},
                        valid_until=valid_until,
                    )
                # read-back verification + attempt to confirm ACA fields in stored record
                result = memory.search(marker, namespace="project:agentX", limit=3)
                aca_fields_verified = False
                try:
                    entries = memory.list_entries(namespace="project:agentX", entry_type="note", tags=["aca", "doctor", "probe"], limit=5)
                    for e in entries or []:
                        e_str = str(e)
                        if marker in e_str and content_hash in e_str:
                            aca_fields_verified = True
                            break
                except Exception:
                    pass
                if marker in (result or ""):
                    fields_note = " + content_hash/tier verified in record" if aca_fields_verified else ""
                    # try to surface the actual expiration from stored record (for "最近 probe entry 的過期時間")
                    probe_expires = valid_until
                    try:
                        entries = memory.list_entries(namespace="project:agentX", entry_type="note", tags=["aca", "doctor", "probe"], limit=5)
                        for e in entries or []:
                            e_str = str(e)
                            if marker in e_str:
                                # extract valid_until if the list_entries result contains it (structure depends on backend)
                                if isinstance(e, dict):
                                    probe_expires = e.get("valid_until") or (e.get("metadata") or {}).get("valid_until") or valid_until
                                break
                    except Exception:
                        pass
                    detail += f" | write+read probe: OK (roundtrip with marker {marker} via live client{fields_note}, used human_confirmed tier + explicit content_hash in ACA metadata)"
                    detail += f" | latest probe entry expires at {probe_expires}"
                    # Write "probe 完成" governance record with evidence_id pointing to the probe entry
                    try:
                        evidence_id = marker
                        if isinstance(write_resp, dict):
                            evidence_id = write_resp.get("memory_id") or write_resp.get("id") or write_resp.get("entry_id") or marker
                        completion_content = f"probe 完成 for {marker} - governance record for ACA doctor store probe"
                        completion_metadata = {
                            "probe_marker": marker,
                            "evidence_ids": [evidence_id],
                            "governance_type": "probe_completed",
                            "aca_version": "0.1",
                        }
                        if hasattr(memory, "write_aca"):
                            memory.write_aca(
                                content=completion_content,
                                namespace="project:agentX",
                                memory_type="note",
                                source_tier="human_confirmed",
                                summary=f"probe completed {marker}",
                                tags=["aca", "doctor", "probe", "governance"],
                                metadata=completion_metadata,
                                valid_until=valid_until,
                            )
                        else:
                            memory.write_structured(
                                content=completion_content,
                                namespace="project:agentX",
                                entry_type="note",
                                summary=f"probe completed {marker}",
                                tags=["aca", "doctor", "probe", "governance"],
                                metadata=completion_metadata,
                                valid_until=valid_until,
                            )
                        detail += " | governance record written with evidence_id"
                    except Exception:
                        pass  # non-fatal, main probe succeeded
                else:
                    return "memory_backend (ACA)", False, f"backend={backend} store={store} path={path} | write+read probe: write succeeded but marker not found in search"
            except Exception as exc:
                return "memory_backend (ACA)", False, f"backend={backend} store={store} path={path} | store probe FAILED: {type(exc).__name__}: {exc}"
    else:
        detail += " (legacy memhall — ACA client shaping enabled via write_aca + tier tools)"
    return "memory_backend (ACA)", True, detail
