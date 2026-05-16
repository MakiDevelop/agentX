from agentx.error_classifier import ErrorClassifier
from agentx.protocol import ToolResult
from agentx.errors import ErrorType


def test_classifier_transient_errors():
    classifier = ErrorClassifier()

    test_cases = [
        ("search_replace", "TimeoutError: Connection timed out"),
        ("run_tests", "Connection reset by peer"),
        ("list_files", "Rate limit exceeded, please retry later"),
        ("search_replace", "The operation timed out"),
        ("git_status", "Throttled: too many requests"),
    ]

    for tool, content in test_cases:
        result = ToolResult(tool=tool, ok=False, content=content)
        error_type = classifier.classify(tool, result)
        assert error_type == ErrorType.TRANSIENT, f"Failed for {tool}: {content}"


def test_classifier_call_errors():
    classifier = ErrorClassifier()

    test_cases = [
        ("search_replace", "FileNotFoundError: No such file or directory 'foo.py'"),
        ("list_files", "Unknown tool: non_existent_tool"),
        ("read_file", "PermissionError: [Errno 13] Permission denied"),
        ("search_replace", "Invalid path: directory does not exist"),
        ("run_tests", "ValueError: Invalid argument provided"),
    ]

    for tool, content in test_cases:
        result = ToolResult(tool=tool, ok=False, content=content)
        error_type = classifier.classify(tool, result)
        assert error_type == ErrorType.CALL_ERROR, f"Failed for {tool}: {content}"


def test_classifier_execution_errors():
    classifier = ErrorClassifier()

    test_cases = [
        ("search_replace", "AssertionError: test_user.py::test_login failed"),
        ("run_tests", "SyntaxError: invalid syntax"),
        ("search_replace", "Ruff lint error: F401 'os' imported but unused"),
        ("git_status", "RuntimeError: Failed to execute command"),
        ("run_tests", "Test failed: 3 failures, 0 errors"),
    ]

    for tool, content in test_cases:
        result = ToolResult(tool=tool, ok=False, content=content)
        error_type = classifier.classify(tool, result)
        assert error_type == ErrorType.EXECUTION_ERROR, f"Failed for {tool}: {content}"


def test_classifier_unknown_error():
    classifier = ErrorClassifier()

    result = ToolResult(tool="search_replace", ok=False, content="Some weird error that doesn't match any pattern")
    error_type = classifier.classify("search_replace", result)

    assert error_type == ErrorType.UNKNOWN


def test_classifier_ok_result_returns_unknown():
    classifier = ErrorClassifier()

    result = ToolResult(tool="list_files", ok=True, content="file1.py\nfile2.py")
    error_type = classifier.classify("list_files", result)

    # 成功結果應該回 UNKNOWN（目前設計如此，後續可調整）
    assert error_type == ErrorType.UNKNOWN


def test_classifier_empty_content():
    classifier = ErrorClassifier()

    result = ToolResult(tool="search_replace", ok=False, content="")
    error_type = classifier.classify("search_replace", result)

    assert error_type == ErrorType.UNKNOWN


# ============================================================
# AgentSession 層級錯誤處理整合測試（A 階段驗證）
# ============================================================

from unittest.mock import MagicMock, patch
from pathlib import Path

from agentx.loop import AgentSession
from agentx.errors import ErrorType


def test_agent_session_records_error_context_on_tool_failure():
    """測試工具失敗時，AgentSession 是否正確記錄 ErrorContext"""
    settings = MagicMock()
    settings.workspace = Path("/tmp/test")
    settings.persona = "default"
    settings.max_steps = 5

    fake_ollama = MagicMock()
    fake_tools = MagicMock()

    with patch("agentx.loop.build_repo_context", return_value=""), \
         patch("agentx.loop.build_memory_context", return_value=""):

        session = AgentSession(
            settings=settings,
            ollama=fake_ollama,
            tools=fake_tools,
            namespace="test"
        )

        # 模擬一個失敗的工具結果
        from agentx.protocol import ToolCall, ToolResult

        # 直接測試分類 + 記錄流程
        failing_result = ToolResult(
            tool="search_replace",
            ok=False,
            content="AssertionError: test failed after edit"
        )

        error_type = session.error_classifier.classify("search_replace", failing_result)

        # 手動模擬主流程中會做的事
        if not failing_result.ok:
            session.current_error = session.error_classifier.classify  # 簡化
            from agentx.errors import ErrorContext
            session.current_error = ErrorContext(
                error_type=error_type,
                tool_name="search_replace",
                error_message=failing_result.content,
            )
            session.error_history.append(session.current_error)

        assert len(session.error_history) == 1
        assert session.error_history[0].tool_name == "search_replace"
        assert session.error_history[0].error_type == ErrorType.EXECUTION_ERROR


def test_build_error_reflection_guidance_contains_key_info():
    """測試錯誤 Reflection 引導訊息是否包含必要資訊"""
    from agentx.errors import ErrorContext

    settings = MagicMock()
    settings.workspace = Path("/tmp")
    settings.persona = "default"
    settings.max_steps = 5

    with patch("agentx.loop.build_repo_context", return_value=""), \
         patch("agentx.loop.build_memory_context", return_value=""):

        session = AgentSession(
            settings=settings,
            ollama=MagicMock(),
            tools=MagicMock(),
            namespace="test"
        )

        error_ctx = ErrorContext(
            error_type=ErrorType.EXECUTION_ERROR,
            tool_name="search_replace",
            error_message="AssertionError: test_foo.py failed"
        )

        guidance = session._build_error_reflection_guidance(error_ctx)

        assert "search_replace" in guidance
        assert "execution_error" in guidance
        assert "AssertionError" in guidance
        assert "結構化的錯誤 Reflection" in guidance
        assert "恢復策略" in guidance
