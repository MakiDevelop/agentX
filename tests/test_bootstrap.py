from pathlib import Path
from typing import Any

from agentx.bootstrap import build_local_instruction_context, build_repo_context
from agentx.loop import AgentSession
from agentx.tools import ToolRegistry, builtin_tools
from helpers import make_settings


class FakeOllama:
    model = "fake"

    def chat(self, *args: Any, **kwargs: Any) -> str:
        return '{"type":"final","content":"done"}'


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return f"search:{namespace}:{limit}:{query}"

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return f"write:{namespace}:{content}"


def test_repo_context_includes_known_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")

    context = build_repo_context(tmp_path)

    assert "README.md" in context
    assert "# Demo" in context
    assert "pyproject.toml" in context


def test_repo_context_includes_agentx_before_readme(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text("LOCAL_CONSTITUTION_MARKER", encoding="utf-8")
    (tmp_path / "README.md").write_text("README_MARKER", encoding="utf-8")

    context = build_repo_context(tmp_path)

    assert "--- AGENTX.md (agentX repo-local instructions) ---" in context
    assert "LOCAL_CONSTITUTION_MARKER" in context
    assert context.index("--- AGENTX.md") < context.index("--- README.md")


def test_local_instruction_context_loads_agent_files_by_priority(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("CLAUDE_MARKER", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("AGENTS_MARKER", encoding="utf-8")
    (tmp_path / "AGENTX.md").write_text("AGENTX_MARKER", encoding="utf-8")

    context = build_local_instruction_context(tmp_path)

    assert "Local instruction priority: AGENTX.md > AGENTS.md > CLAUDE.md" in context
    assert "cannot override safety policy" in context
    assert context.index("--- AGENTX.md") < context.index("--- AGENTS.md")
    assert context.index("--- AGENTS.md") < context.index("--- CLAUDE.md")
    assert "AGENTX_MARKER" in context
    assert "AGENTS_MARKER" in context
    assert "CLAUDE_MARKER" in context


def test_local_instruction_context_empty_when_no_instruction_files(tmp_path: Path) -> None:
    assert build_local_instruction_context(tmp_path) == ""


def test_repo_context_loads_handoff_files(tmp_path: Path) -> None:
    handoff = tmp_path / ".agentx" / "handoff"
    handoff.mkdir(parents=True)
    (handoff / "NEXT_SESSION.md").write_text("NEXT_SESSION_MARKER", encoding="utf-8")
    (handoff / "CONVERSATION_HANDOFF.md").write_text("CONVERSATION_MARKER", encoding="utf-8")

    context = build_repo_context(tmp_path)

    assert "--- .agentx/handoff/NEXT_SESSION.md ---" in context
    assert "NEXT_SESSION_MARKER" in context
    assert "--- .agentx/handoff/CONVERSATION_HANDOFF.md ---" in context
    assert "CONVERSATION_MARKER" in context


def test_repo_context_missing_files_is_safe_and_includes_inventory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text("print('demo')\n", encoding="utf-8")

    context = build_repo_context(tmp_path)

    assert context.startswith(f"Workspace: {tmp_path}")
    assert "--- git status ---" in context
    assert "--- file inventory ---" in context
    assert "src/demo.py" in context


def test_repo_context_truncates_per_file_and_total_context(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text("A" * 3100 + "TAIL_MARKER", encoding="utf-8")

    context = build_repo_context(tmp_path, max_chars=12000)
    capped = build_repo_context(tmp_path, max_chars=150)

    assert "A" * 3000 in context
    assert "TAIL_MARKER" not in context
    assert len(capped) <= 150


def test_agent_session_initial_messages_include_repo_bootstrap(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text("SESSION_BOOTSTRAP_MARKER", encoding="utf-8")
    memory = FakeMemory()
    settings = make_settings(tmp_path, learning_enabled=False)
    tools = ToolRegistry(builtin_tools(tmp_path, memory))  # type: ignore[arg-type]

    session = AgentSession(
        settings=settings,
        ollama=FakeOllama(),  # type: ignore[arg-type]
        tools=tools,
        memory=memory,  # type: ignore[arg-type]
    )

    bootstrap_messages = [
        message["content"]
        for message in session.messages
        if message["content"].startswith("Repo bootstrap context:")
    ]
    assert len(bootstrap_messages) == 1
    assert "SESSION_BOOTSTRAP_MARKER" in bootstrap_messages[0]
