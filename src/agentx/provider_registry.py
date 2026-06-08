"""Provider Registry for LLM backends (Provider Registry Pattern).

Borrowed/adapted from earendil-works/pi (packages/ai/src/api-registry.ts).

Purpose:
- Central place to register different LLM providers (Ollama, llama.cpp, future OpenAI,
  Anthropic, etc.).
- Allows adding a third (or Nth) backend without touching the central client creation
  logic in cli.py or elsewhere.
- Currently only two backends exist, so the registry is lightweight. The old
  AGENTX_BACKEND env switch is preserved for compatibility.

Usage:
    from agentx.provider_registry import get_llm_client, register_llm_backend

    # In each backend module (at bottom):
    register_llm_backend("ollama", OllamaClient)
    register_llm_backend("llama_cpp", LlamaCppClient)

    # In cli.py or other creation site:
    client = get_llm_client(backend, base_url, model, timeout)

The registry stores *factories* (callables that take base_url, model, timeout and
return a fresh client instance). This avoids holding live client state in the registry.
"""

from __future__ import annotations

from typing import Callable, Dict, Protocol, Sequence



class LLMClient(Protocol):
    """Common protocol that all LLM backends must satisfy.

    This is the Python equivalent of pi's ApiProvider / stream/complete contracts.
    """

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        on_delta: Callable[[str], None] | None = None,
        cancel_event: object | None = None,
    ) -> str:
        """Send chat messages and return the final assistant content.

        If on_delta is provided, the backend should stream tokens via the callback.
        cancel_event (threading.Event) can be used for cooperative cancellation.
        """
        ...

    def list_models(self) -> list[str]:
        """Return list of available model names for this backend."""
        ...

    def close(self) -> None:
        """Release any resources (http clients, etc.)."""
        ...

    # Context manager support is nice-to-have and implemented by current backends.
    def __enter__(self) -> "LLMClient": ...
    def __exit__(self, *args: object) -> None: ...


# Internal registry: backend_name -> factory(base_url, model, timeout) -> LLMClient
_registry: Dict[str, Callable[[str, str, float], LLMClient]] = {}


def register_llm_backend(
    name: str,
    factory: Callable[[str, str, float], LLMClient],
    *,
    source_id: str | None = None,
) -> None:
    """Register a new LLM backend.

    Args:
        name: The key used with AGENTX_BACKEND (e.g. "ollama", "llama_cpp", "openai").
        factory: Callable that constructs a client instance given (base_url, model, timeout).
        source_id: Optional identifier for who registered it (useful for extensions /
                   future unregister in more advanced scenarios, following pi's design).
    """
    if name in _registry:
        # Allow re-registration (e.g. during tests or reloads), but warn in spirit of pi.
        pass
    _registry[name] = factory


def resolve_llm_backend(name: str) -> Callable[[str, str, float], LLMClient]:
    """Resolve the factory for a backend name. Raises if unknown."""
    if name not in _registry:
        available = ", ".join(sorted(_registry.keys())) or "(none)"
        raise ValueError(f"No LLM backend registered for '{name}'. Available: {available}")
    return _registry[name]


def get_llm_client(
    name: str,
    base_url: str,
    model: str,
    timeout: float = 120.0,
) -> LLMClient:
    """Convenience: resolve + instantiate in one call.

    This is the primary API used by build_runtime and similar.
    """
    factory = resolve_llm_backend(name)
    return factory(base_url, model, timeout)


def list_registered_backends() -> list[str]:
    """Return currently registered backend names (for diagnostics / doctor)."""
    return sorted(_registry.keys())


def register_builtin_backends() -> None:
    """Explicitly import the two built-in backends so their self-registration runs.

    Call this (or just `import agentx.cli`) if you want to guarantee that
    "ollama" and "llama_cpp" are always available via get_llm_client() even
    in environments that only import specific submodules.
    """
    import agentx.ollama  # noqa: F401
    import agentx.llama_cpp  # noqa: F401


# Self-registration is done at the bottom of ollama.py and llama_cpp.py so that
# simply importing the backend modules populates the registry.
# This keeps the registry itself free of hard dependencies on concrete clients.
