from agentx.bootstrap import build_memory_context


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"{namespace}:{limit}:{query}"


def test_memory_context_searches_project_agent_and_shared() -> None:
    context = build_memory_context(FakeMemory(), "project:agentX", "agentX")

    assert "--- memory project:agentX ---" in context
    assert "--- memory agent:agentx ---" in context
    assert "--- memory shared ---" in context
