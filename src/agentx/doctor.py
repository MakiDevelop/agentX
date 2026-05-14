from __future__ import annotations

import subprocess

from agentx.config import Settings
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient


def run_doctor(settings: Settings, memory: MemoryHallClient, ollama: OllamaClient) -> list[tuple[str, bool, str]]:
    checks = [
        _check_command("uv", ["uv", "--version"]),
        _check_command("git", ["git", "status", "--short", "--branch"], cwd=settings.workspace),
        _check_ollama(settings, ollama),
        _check_model(settings, ollama),
        _check_memory_search(memory),
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
