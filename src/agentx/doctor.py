from __future__ import annotations

import subprocess

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
