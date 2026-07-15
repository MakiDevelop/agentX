import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from agentx.bootstrap import build_local_instruction_context, build_repo_context, local_instructions_payload
from agentx.cli import app
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


def test_local_instructions_payload_reports_priority_and_content(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("CLAUDE_MARKER", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("AGENTS_MARKER", encoding="utf-8")
    (tmp_path / "AGENTX.md").write_text("AGENTX_MARKER", encoding="utf-8")

    payload = local_instructions_payload(tmp_path)

    assert payload["schema"] == "agentx.local_instructions.v1"
    assert payload["ok"] is True
    assert payload["priority"] == ["AGENTX.md", "AGENTS.md", "CLAUDE.md"]
    assert payload["selected_file"] == "AGENTX.md"
    assert payload["found_count"] == 3
    assert [item["name"] for item in payload["files"]] == ["AGENTX.md", "AGENTS.md", "CLAUDE.md"]
    assert "AGENTX_MARKER" in payload["context"]
    assert payload["warnings"] == []


def test_local_instructions_payload_truncates_content(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text("A" * 20, encoding="utf-8")

    payload = local_instructions_payload(tmp_path, per_file_chars=5, max_chars=80)

    agentx = payload["files"][0]
    assert agentx["included_chars"] == 5
    assert agentx["truncated"] is True
    assert agentx["content_excerpt"] == "A" * 5
    assert payload["context_truncated"] is True


def test_local_instructions_payload_warns_when_none_found(tmp_path: Path) -> None:
    payload = local_instructions_payload(tmp_path)

    assert payload["ok"] is True
    assert payload["selected_file"] is None
    assert payload["found_count"] == 0
    assert payload["context"] == ""
    assert payload["warnings"] == ["no_local_instruction_files_found"]


def test_instructions_cli_outputs_jsonl_event(tmp_path: Path) -> None:
    (tmp_path / "AGENTX.md").write_text("CLI_MARKER", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "instructions",
            "--workspace",
            str(tmp_path),
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "instructions"
    assert envelope["data"]["schema"] == "agentx.local_instructions.v1"
    assert envelope["data"]["selected_file"] == "AGENTX.md"
    assert "CLI_MARKER" in envelope["data"]["context"]


def test_instructions_cli_uses_current_workspace_by_default(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "AGENTX.md").write_text("DEFAULT_WORKSPACE_MARKER", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["instructions", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.local_instructions.v1"
    assert payload["workspace"] == str(tmp_path)
    assert "DEFAULT_WORKSPACE_MARKER" in payload["context"]


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
