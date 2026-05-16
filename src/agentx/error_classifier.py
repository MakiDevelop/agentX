from __future__ import annotations

import re
from typing import Optional

from agentx.errors import ErrorType
from agentx.protocol import ToolResult


class ErrorClassifier:
    """
    錯誤分類器（規則為主版本）

    目前採用關鍵字 + Exception 名稱進行分類，
    後續階段可擴充更複雜的規則或輕量 LLM 輔助。
    """

    # 暫時性錯誤關鍵字（可重試）
    TRANSIENT_KEYWORDS = [
        "timeout",
        "timed out",
        "connection",
        "connection reset",
        "rate limit",
        "too many requests",
        "locked",
        "temporarily unavailable",
        "retry",
        "throttl",
    ]

    # 呼叫錯誤關鍵字（參數、路徑、工具不存在等）
    CALL_ERROR_KEYWORDS = [
        "no such file",
        "file not found",
        "not found",
        "permission denied",
        "invalid path",
        "does not exist",
        "unknown tool",
        "invalid argument",
        "missing required",
    ]

    # 執行錯誤關鍵字（程式碼執行相關）
    EXECUTION_ERROR_KEYWORDS = [
        "assertionerror",
        "syntaxerror",
        "indentationerror",
        "test failed",
        "failed:",
        "error:",
        "traceback",
        "runtime error",
        "lint error",
        "mypy",
        "ruff",
    ]

    def classify(self, tool_name: str, result: ToolResult) -> ErrorType:
        """
        根據工具名稱與 ToolResult 進行錯誤分類。
        """
        if result.ok:
            return ErrorType.UNKNOWN

        content = (result.content or "").lower()
        exception_name = self._extract_exception_name(result.content).lower()

        # 1. 先判斷是否為暫時性錯誤
        if self._is_transient(content, exception_name):
            return ErrorType.TRANSIENT

        # 2. 判斷是否為呼叫錯誤
        if self._is_call_error(content, exception_name, tool_name):
            return ErrorType.CALL_ERROR

        # 3. 判斷是否為執行錯誤
        if self._is_execution_error(content, exception_name):
            return ErrorType.EXECUTION_ERROR

        # 4. 預設未知
        return ErrorType.UNKNOWN

    def _extract_exception_name(self, content: Optional[str]) -> str:
        """從錯誤訊息中嘗試提取 Exception 名稱，例如 'TimeoutError: ...'"""
        if not content:
            return ""
        # 常見格式："TimeoutError: ..." 或 "FileNotFoundError: ..."
        match = re.match(r"^([A-Za-z]+Error)", content.strip())
        return match.group(1) if match else ""

    def _is_transient(self, content: str, exception_name: str) -> bool:
        text = f"{content} {exception_name}"
        return any(keyword in text for keyword in self.TRANSIENT_KEYWORDS)

    def _is_call_error(self, content: str, exception_name: str, tool_name: str) -> bool:
        text = f"{content} {exception_name} {tool_name.lower()}"
        if any(keyword in text for keyword in self.CALL_ERROR_KEYWORDS):
            return True

        # 常見的呼叫相關 Exception
        call_exceptions = {"filenotfounderror", "permissionerror", "valueerror", "typeerror"}
        return exception_name in call_exceptions

    def _is_execution_error(self, content: str, exception_name: str) -> bool:
        text = f"{content} {exception_name}"
        if any(keyword in text for keyword in self.EXECUTION_ERROR_KEYWORDS):
            return True

        # 常見執行錯誤
        exec_exceptions = {"assertionerror", "syntaxerror", "indentationerror", "runtimeerror"}
        return exception_name in exec_exceptions
