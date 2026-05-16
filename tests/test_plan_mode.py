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
        self.last_messages: list[dict] = []

    def chat(self, messages, json_mode=False, cancel_event=None):  # noqa: ANN001
        self.last_messages = list(messages)
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


def test_plan_only_corrective_message_contains_structured_guidance() -> None:
    """
    When plan_only=True and the model attempts a tool call,
    the corrective message fed back to the model must contain structured planning guidance.
    """
    fake_ollama = FakeOllama(
        [
            # First response tries to call a tool → should be blocked
            '{"type":"tool_call","tool":"list_files","args":{}}',
            # Second response finally gives a final answer
            '{"type":"final","content":"已產出結構化方案。"}',
        ]
    )
    fake_tools = FakeToolRegistry()

    with patch("agentx.loop.build_repo_context", return_value="repo"), \
         patch("agentx.loop.build_memory_context", return_value="mem"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=5, workspace=Path("/tmp")),
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        session.ask("規劃重構", plan_only=True)

    # The second message sent back should be the corrective structured guidance
    assert len(fake_ollama.last_messages) >= 2
    corrective = fake_ollama.last_messages[-1].get("content", "")
    assert "PLAN MODE" in corrective
    assert "結構化" in corrective or "步驟" in corrective
    assert "風險" in corrective or "依賴" in corrective
    assert "驗證" in corrective


def test_build_status_line_shows_plan_marker() -> None:
    """build_status_line should clearly indicate PLAN mode in the status bar."""
    from agentx.cli import build_status_line

    normal = build_status_line("gemma4:31b", False, 45)
    plan = build_status_line("gemma4:31b", True, 45)

    assert "PLAN" not in normal
    assert "PLAN" in plan
    assert "gemma4:31b | PLAN | context 45%" == plan
    assert "context 45%" in normal
    assert "context 45%" in plan
