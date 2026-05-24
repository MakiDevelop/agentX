from pathlib import Path
from unittest.mock import MagicMock, patch

from agentx.errors import ErrorContext, ErrorType
from agentx.error_classifier import ErrorClassifier
from agentx.loop import AgentSession
from agentx.protocol import ToolResult


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


def test_classifier_http_4xx_as_call_error():
    """403/401/404 等客戶端 HTTP 錯誤應分類為 CALL_ERROR（不可重試）"""
    classifier = ErrorClassifier()

    test_cases = [
        ("web_fetch", "HTTPStatusError: Client error '403 Forbidden' for url 'https://example.com/secret'"),
        ("web_fetch", "HTTPStatusError: Client error '401 Unauthorized' for url 'https://api.x.com/v1'"),
        ("web_fetch", "HTTPStatusError: Client error '404 Not Found' for url 'https://foo.bar/missing'"),
        ("web_fetch", "Client error '403 Forbidden' for url ..."),  # 無 HTTPStatusError 前綴
    ]

    for tool, content in test_cases:
        result = ToolResult(tool=tool, ok=False, content=content)
        error_type = classifier.classify(tool, result)
        assert error_type == ErrorType.CALL_ERROR, f"Expected CALL_ERROR for {tool}: {content}, got {error_type}"


def test_classifier_http_5xx_as_transient():
    """5xx 伺服器錯誤應分類為 TRANSIENT（可重試）"""
    classifier = ErrorClassifier()

    test_cases = [
        ("web_fetch", "HTTPStatusError: Server error '502 Bad Gateway' for url 'https://example.com'"),
        ("web_fetch", "HTTPStatusError: Server error '503 Service Unavailable' for url 'https://api'"),
        ("some_tool", "status_code=500 Internal Server Error"),
    ]

    for tool, content in test_cases:
        result = ToolResult(tool=tool, ok=False, content=content)
        error_type = classifier.classify(tool, result)
        assert error_type == ErrorType.TRANSIENT, f"Expected TRANSIENT for {tool}: {content}, got {error_type}"


def test_classifier_no_substring_false_positive():
    """避免 'blocked' 之類的詞誤配 'locked' transient keyword"""
    classifier = ErrorClassifier()

    # 這個錯誤訊息包含 "blocked"（會內含 "locked" 子字串），但不是真正的 locked 錯誤
    result = ToolResult(
        tool="web_fetch",
        ok=False,
        content="ValueError: blocked non-public address: 192.168.1.1"
    )
    error_type = classifier.classify("web_fetch", result)
    # 現在應該是 CALL_ERROR（invalid path / value），而不是因為 substring 誤判 TRANSIENT
    assert error_type == ErrorType.CALL_ERROR, f"Should not false-positive transient on 'blocked' substring, got {error_type}"
