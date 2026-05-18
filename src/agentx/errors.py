from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ErrorType(str, Enum):
    """錯誤類型分類（階段一先使用規則為主）"""

    TRANSIENT = "transient"                    # 暫時性錯誤（可重試）
    CALL_ERROR = "call_error"                  # 工具呼叫錯誤（參數、路徑、型別等）
    EXECUTION_ERROR = "execution_error"        # 執行邏輯錯誤（測試失敗、語法錯誤等）
    REQUIREMENT_MISUNDERSTAND = "requirement_misunderstand"  # 需求理解錯誤
    STUCK = "stuck"                            # 陷入重複失敗狀態
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """單次錯誤的上下文記錄"""

    error_type: ErrorType
    tool_name: str
    error_message: str
    attempt_count: int = 1
    last_error_at: datetime = field(default_factory=datetime.now)

    # 後續階段可擴充：
    # suggested_recovery: Optional[RecoveryAction] = None
    # related_task_ids: list[int] = field(default_factory=list)


class RecoveryAction(str, Enum):
    """可建議的恢復動作類型（Phase B2 成熟化版本）"""

    RETRY = "retry"                           # 直接重試
    RETRY_WITH_FIX = "retry_with_fix"         # 修正參數/輸入後重試
    BACKTRACK = "backtrack"                   # 回退最近的修改
    CHANGE_STRATEGY = "change_strategy"       # 改用不同技術/流程
    SIMPLIFY_SCOPE = "simplify_scope"         # 把任務拆小、降低複雜度
    VERIFY_ASSUMPTION = "verify_assumption"   # 先驗證某個假設（讀檔、跑小測試）
    REQUEST_CLARIFICATION = "request_clarification"  # 詢問使用者需求
    ESCALATE_TO_USER = "escalate_to_user"     # 請求人類介入
    REPRIORITIZE = "reprioritize"             # 調整任務優先序
    REFLECT_AND_ADJUST = "reflect_and_adjust" # 深度 Reflection 後調整計劃
    ABANDON_AND_RESTART = "abandon_and_restart"  # 放棄目前方向，從頭用新方案


@dataclass
class RecoverySuggestion:
    """單一恢復建議"""

    action: RecoveryAction
    description: str                    # 給模型看的建議說明
    rationale: str = ""                 # 為什麼建議這個動作
    confidence: float = 0.0             # 系統對這個建議的信心 (0~1)
    human_readable: str = ""            # 給人類看的版本（未來用）
