from pathlib import Path
from unittest.mock import MagicMock, patch

from agentx.cli import SLASH_COMMANDS, format_plan_status
from agentx.loop import AgentSession


def test_format_plan_status_on() -> None:
    assert "on" in format_plan_status(True)
    assert "只討論方案" in format_plan_status(True)


def test_format_plan_status_off() -> None:
    assert format_plan_status(False) == "off"


def test_plan_command_is_registered() -> None:
    commands = [cmd for cmd, _ in SLASH_COMMANDS]
    assert "/plan" in commands

    desc = dict(SLASH_COMMANDS)["/plan"]
    assert "plan 模式" in desc
    assert "只討論方案" in desc


class FakeOllama:
    """Minimal fake that returns predetermined JSON responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.call_count = 0

    def chat(self, messages, json_mode=False, cancel_event=None):  # noqa: ANN001
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


class FakeMemory:
    def search(self, query: str, namespace: str = "shared", limit: int = 5) -> str:
        return ""

    def write(self, content: str, namespace: str = "agent:agentx") -> str:
        return ""


class FakeToolRegistry:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.memory = MagicMock()  # required by AgentSession bootstrap

    def run(self, tool: str, args: dict) -> object:  # noqa: ANN001
        self.executed.append(tool)
        return MagicMock(ok=True, content=f"executed:{tool}")


def test_agent_session_plan_only_blocks_tool_call() -> None:
    """
    When plan_only=True, if the model outputs a tool_call,
    AgentSession should NOT execute the tool and should instead
    feed back a corrective message forcing a final answer.
    """
    fake_ollama = FakeOllama(
        [
            # First response: model wrongly tries to call a tool
            '{"type":"tool_call","tool":"list_files","args":{"path":"."}}',
            # Second response: model now correctly gives final answer
            '{"type":"final","content":"My plan is to first list files then read README."}',
        ]
    )
    fake_tools = FakeToolRegistry()

    with patch("agentx.loop.build_repo_context", return_value="fake repo context"), \
         patch("agentx.loop.build_memory_context", return_value="fake memory context"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=5, workspace=Path("/tmp/test")),
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        result = session.ask("幫我規劃如何審查這個 repo", plan_only=True)

    # Tool should never have been executed
    assert "list_files" not in fake_tools.executed
    assert "My plan is to first list files" in result
    assert fake_ollama.call_count == 2  # model was given a second chance


def test_agent_session_normal_mode_still_executes_tools() -> None:
    """Sanity check: when plan_only=False (default), tools are still executed."""
    fake_ollama = FakeOllama(
        ['{"type":"tool_call","tool":"git_status","args":{}}']
    )
    fake_tools = FakeToolRegistry()

    with patch("agentx.loop.build_repo_context", return_value="fake repo context"), \
         patch("agentx.loop.build_memory_context", return_value="fake memory context"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=3, workspace=Path("/tmp/test")),
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        # We expect it to return early via the direct tool path or after execution.
        # The important point is that the tool registry was called.
        session.ask("git status 一下", plan_only=False)

    assert "git_status" in fake_tools.executed
