from pathlib import Path
from typing import Any
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
        if self.call_count >= len(self.responses):
            return '{"type":"final","content":"(plan_mode test fallback)"}'
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

    def run(self, tool: str, args: dict, **kwargs: Any) -> object:  # noqa: ANN001
        # Accept _return_effective (and future internal flags) for compatibility with
        # real ToolRegistry after Codex feedback fixes to run() signature.
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
    # Tsumu _direct_tool_call change: now exact match `== "git status"`, and has
    # length/write guards. "git status 一下" no longer short-circuits, so the ask
    # will do at least one real ollama.chat. Provide enough + disable learning.
    fake_ollama = FakeOllama(
        ['{"type":"tool_call","tool":"git_status","args":{}}', '{"type":"final","content":"done"}']
    )
    fake_tools = FakeToolRegistry()

    settings = MagicMock(model="test", persona="default", max_steps=3, workspace=Path("/tmp/test"))
    settings.learning_enabled = False

    with patch("agentx.loop.build_repo_context", return_value="fake repo context"), \
         patch("agentx.loop.build_memory_context", return_value="fake memory context"):

        session = AgentSession(
            settings=settings,
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        # The important point is that the tool registry was called (via normal path now).
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


def test_agent_session_respects_internal_plan_only_state() -> None:
    """AgentSession should use self.plan_only when plan_only is not explicitly passed to ask()."""
    fake_ollama = FakeOllama(
        [
            '{"type":"tool_call","tool":"list_files","args":{}}',
            '{"type":"final","content":"Plan acknowledged."}',
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

        # Set internal state instead of passing parameter
        session.plan_only = True

        session.ask("規劃一下", plan_only=None)  # explicitly not overriding

    assert "list_files" not in fake_tools.executed  # tool should have been blocked
    assert fake_ollama.call_count == 2


def test_execute_disables_plan_only_and_injects_message() -> None:
    """Simulate what /execute does: disable plan_only and inject execution context message."""
    with patch("agentx.loop.build_repo_context", return_value="repo"), \
         patch("agentx.loop.build_memory_context", return_value="mem"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=5, workspace=Path("/tmp")),
            ollama=MagicMock(),
            tools=MagicMock(),
            namespace="test",
        )

        # Simulate being in plan mode
        session.plan_only = True
        assert session.plan_only is True

        # Simulate /execute behavior
        session.plan_only = False
        execute_msg = (
            "規劃階段已結束。使用者已同意上述方案。\n"
            "現在請切換至執行模式，使用工具逐步完成方案中的每個步驟。"
        )
        session.messages.append({"role": "system", "content": execute_msg})

        assert session.plan_only is False
        last_msg = session.messages[-1]
        assert last_msg["role"] == "system"
        assert "規劃階段已結束" in last_msg["content"]
        assert "執行模式" in last_msg["content"]


def test_plan_mode_prompt_includes_execute_suggestion() -> None:
    """The plan mode prompt should instruct the model to proactively suggest /execute when planning is complete."""
    planning_guidance = (
        "當你認為規劃已經完整、足夠具體、可執行時，請在 final answer 的最後主動建議使用者輸入 `/execute`"
    )

    from agentx import cli
    cli_source = open(cli.__file__, encoding="utf-8").read()
    assert planning_guidance in cli_source


def test_natural_execute_trigger_detection() -> None:
    """Basic check for natural language execute triggers."""
    from agentx.cli import is_natural_execute_trigger

    assert is_natural_execute_trigger("現在執行吧")
    assert is_natural_execute_trigger("go ahead")
    assert is_natural_execute_trigger("照這個方案做")
    assert not is_natural_execute_trigger("繼續討論")
    assert not is_natural_execute_trigger("plan 一下")


def test_reflection_loop_guard_triggers_warning() -> None:
    """
    When the model outputs 3+ consecutive Reflect actions without tool calls in between,
    the Reflection Loop Guard should inject a strong system warning message forcing progress.
    This is critical for headless stability with local models.
    """
    # Model keeps reflecting → each reflect triggers 2 ollama calls (action + _reflect free-text)
    # Provide plenty of responses so 3+ consecutive model reflects can complete without IndexError
    responses = ['{"type":"reflect","focus":"loop test"}'] * 10 + [
        '{"type":"final","content":"最終方案：先讀取關鍵檔案再決定。"}'
    ]
    fake_ollama = FakeOllama(responses)
    fake_tools = FakeToolRegistry()

    with patch("agentx.loop.build_repo_context", return_value="repo"), \
         patch("agentx.loop.build_memory_context", return_value="mem"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=10, workspace=Path("/tmp")),
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        # Normal mode (not plan_only) to avoid extra plan forcing logic
        result = session.ask("請規劃一個複雜的重構任務", plan_only=False)

    # Guard should have fired (injected system message with the text)
    guard_triggered = any(
        "Reflection Loop Guard" in (m.get("content", "") if isinstance(m, dict) else str(m))
        for m in session.messages
    )
    assert guard_triggered, "Reflection loop guard message was not injected to session.messages after 3+ consecutive reflects"

    # Final result should still be produced
    assert "最終方案" in result


def test_reflection_loop_guard_in_plan_only_uses_plan_specific_message() -> None:
    """
    In plan_only mode, when guard triggers, the injected message must:
    - Contain 'PLAN MODE' variant text
    - Encourage producing 'final 方案' (structured plan)
    - NOT encourage executing tools (e.g. no 'search_replace' or '執行工具')
    This addresses Codex review feedback on plan mode semantics.
    """
    responses = ['{"type":"reflect","focus":"plan loop"}'] * 8 + [
        '{"type":"final","content":"完整規劃方案已產出。"}'
    ]
    fake_ollama = FakeOllama(responses)
    fake_tools = FakeToolRegistry()

    with patch("agentx.loop.build_repo_context", return_value="repo"), \
         patch("agentx.loop.build_memory_context", return_value="mem"):

        session = AgentSession(
            settings=MagicMock(model="test", persona="default", max_steps=15, workspace=Path("/tmp")),
            ollama=fake_ollama,  # type: ignore[arg-type]
            tools=fake_tools,  # type: ignore[arg-type]
            namespace="test",
        )

        session.ask("規劃複雜任務", plan_only=True)

    # Find the guard message(s)
    guard_messages = [
        m.get("content", "") for m in session.messages
        if isinstance(m, dict) and "Reflection Loop Guard" in m.get("content", "")
    ]
    assert len(guard_messages) >= 1, "No guard message found in plan_only run"

    guard_text = guard_messages[0]
    assert "PLAN MODE" in guard_text or "plan mode" in guard_text.lower()
    assert "final 方案" in guard_text or "完整" in guard_text
    # Should explicitly tell model NOT to suggest tool execution in plan mode
    assert "不要建議執行工具" in guard_text or "plan mode 禁止" in guard_text
    # Should NOT contain the positive "execute tool" encouragement from normal mode
    assert "或執行下一個具體的工具行動" not in guard_text
    assert "search_replace" not in guard_text
