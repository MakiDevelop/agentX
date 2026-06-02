from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agentx.errors import ErrorContext, ErrorType, RecoveryAction, RecoverySuggestion


@dataclass
class RecoveryRecord:
    """記錄一次恢復建議的應用（供 observability 與未來學習使用）"""
    timestamp: datetime = field(default_factory=datetime.now)
    error_type: ErrorType = ErrorType.UNKNOWN
    tool_name: str = ""
    suggested_actions: list[str] = field(default_factory=list)
    chosen_action: str | None = None
    was_successful: bool | None = None


class RecoveryPlaybook:
    """
    錯誤恢復策略 Playbook（Phase B2 完整成熟化版本）。

    強化重點：
    - 偵測「同檔案連續失敗」（最常見的 headless 卡住模式）
    - 偵測「工具震盪」（在兩個工具間來回失敗）
    - 任務感知：有進行中任務時會建議調整優先序或標記阻礙
    - 更精準、對本地弱模型友善的建議文字
    - 提供 RecoveryRecord 供外部觀測上次建議
    """

    def __init__(self):
        self.last_record: RecoveryRecord | None = None

    def generate_suggestions(
        self,
        error_ctx: ErrorContext,
        error_history: list[ErrorContext],
        tasks: list[dict[str, Any]] | None = None,
    ) -> list[RecoverySuggestion]:
        """
        產生優先序恢復建議（最多 3 條，由高信心到低）。
        同時更新 self.last_record 供外部觀測。
        """
        suggestions: list[RecoverySuggestion] = []
        recent = error_history[-7:] if error_history else []
        total_errors = len(error_history)

        same_tool_count = sum(1 for e in recent if e.tool_name == error_ctx.tool_name)
        same_type_count = sum(1 for e in recent if e.error_type == error_ctx.error_type)

        # === 進階模式偵測 ===
        same_file_count = self._count_same_file_failures(recent, error_ctx)
        is_oscillating = self._is_tool_oscillating(recent)

        has_active_tasks = bool(tasks) and any(t.get("status") == "in_progress" for t in (tasks or []))

        # === 優先級 1：同檔案連續失敗（最危險的 headless 模式）===
        if same_file_count >= 3:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.BACKTRACK,
                description=f"你已經對同一個檔案/位置連續失敗 {same_file_count} 次。強烈建議先用 git diff 或 read_file 確認最近修改，再考慮 BACKTRACK。（Gemma4 等小模型特別容易在同位置重複失敗，驗證現況是脫困第一步）",
                rationale="同檔案連續 edit 失敗是本地模型最常陷入的死循環。",
                confidence=0.88,
            ))

        # === 優先級 2：明顯 STUCK（同工具 + 同類型）===
        if same_tool_count >= 3 and same_type_count >= 3:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.BACKTRACK,
                description=f"連續在 `{error_ctx.tool_name}` 上遇到相同錯誤，建議立即 BACKTRACK 最近修改。（Gemma4 等弱模型 format drift 常見，驗證比繼續 edit 更重要）",
                rationale="同工具同類型錯誤 ≥3 次，幾乎一定是最近變更引入的問題。",
                confidence=0.86,
            ))
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.SIMPLIFY_SCOPE,
                description="把目前正在處理的任務拆小，先只解決這個錯誤相關的最小部分。（對小模型尤其有效，避免 token 浪費在無效重試）",
                rationale="複雜任務 + 連續失敗時，拆小是最有效的脫困方式。",
                confidence=0.77,
            ))

        # === 優先級 3：工具震盪 ===
        if is_oscillating:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.CHANGE_STRATEGY,
                description="你似乎在兩個工具之間來回切換卻都失敗。建議停下來做一次完整 Reflection，決定只用其中一種做法徹底解決。",
                rationale="工具震盪通常代表策略層面的混亂。",
                confidence=0.81,
            ))

        # === 優先級 4：執行錯誤主導 ===
        if error_ctx.error_type == ErrorType.EXECUTION_ERROR:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.VERIFY_ASSUMPTION,
                description="先用 read_file 或 run_tests 驗證你對目前程式狀態的假設，再繼續修改。（Gemma4 等小模型容易「以為成功但實際有細節遺漏」，驗證是必要習慣）",
                rationale="執行錯誤多半來自對現況的錯誤認知。",
                confidence=0.75,
            ))
            if same_tool_count >= 2:
                suggestions.append(RecoverySuggestion(
                    action=RecoveryAction.CHANGE_STRATEGY,
                    description="直接修改似乎一直失敗，建議改用「先寫小測試 → 再修改」的節奏。",
                    rationale="盲目 search_replace 在複雜情境下很容易越改越亂。",
                    confidence=0.73,
                ))

        # === 優先級 5：呼叫層錯誤 ===
        if error_ctx.error_type == ErrorType.CALL_ERROR:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.RETRY_WITH_FIX,
                description="這是呼叫錯誤（路徑、參數、工具不存在）。請先執行 list_files 或 read_file 確認實際狀態，再修正呼叫。",
                rationale="呼叫錯誤幾乎 100% 是模型對當前檔案系統的認知與實際不符。",
                confidence=0.82,
            ))

        # === 優先級 6：暫時性錯誤 ===
        if error_ctx.error_type == ErrorType.TRANSIENT:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.RETRY,
                description="暫時性問題（超時、鎖定、連線）。建議等待 1-2 秒後直接重試同樣呼叫。",
                rationale="暫時性錯誤重試成功率通常很高。",
                confidence=0.68,
            ))

        # === 優先級 7：長時間卡住 + 有進行中任務 ===
        if total_errors >= 6:
            if has_active_tasks:
                suggestions.append(RecoverySuggestion(
                    action=RecoveryAction.REPRIORITIZE,
                    description="目前任務卡太久，建議先用 task_update 把這個卡住的任務標記為 blocked，並先推進其他較簡單的任務。",
                    rationale="長時間單一任務卡住會讓整個 session 失控。",
                    confidence=0.79,
                ))
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.ESCALATE_TO_USER,
                description="已多次恢復失敗。請現在輸出 reflect，把錯誤歷史、已嘗試策略、目前任務狀態整理清楚後請求人類協助。",
                rationale="超過 6 次錯誤且多次 playbook 建議仍失敗時，人類是最後有效手段。",
                confidence=0.93,
            ))

        # === 保底 ===
        if not suggestions:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.REFLECT_AND_ADJUST,
                description="進行一次結構化 Reflection，清楚寫出：這個錯誤的根本原因 + 你接下來要改變的具體策略。",
                rationale="沒有明顯模式時，誠實 Reflection 是最安全的動作。",
                confidence=0.58,
            ))

        # 記錄這次建議
        self.last_record = RecoveryRecord(
            error_type=error_ctx.error_type,
            tool_name=error_ctx.tool_name,
            suggested_actions=[s.action.value for s in suggestions],
        )

        return sorted(suggestions, key=lambda s: s.confidence, reverse=True)[:3]

    # === 內部輔助偵測 ===
    def _count_same_file_failures(self, recent: list[ErrorContext], current: ErrorContext) -> int:
        """簡單啟發式：從錯誤訊息中猜測是否在同一個檔案上連續失敗"""
        count = 0
        for e in recent:
            if e.tool_name != current.tool_name:
                continue
            # 常見模式："search_replace on path/to/file.py" 或錯誤訊息裡出現相同路徑
            if any(token in (e.error_message or "").lower() for token in [".py", ".ts", ".js", "file", "path"]):
                count += 1
        return max(count, 1 if current.tool_name in ("search_replace", "insert_code") else 0)

    def _is_tool_oscillating(self, recent: list[ErrorContext]) -> bool:
        """偵測是否在兩個工具之間來回失敗"""
        if len(recent) < 4:
            return False
        tools = [e.tool_name for e in recent[-6:]]
        unique = set(tools)
        if len(unique) != 2:
            return False
        # 簡單檢查是否交替出現
        a, b = list(unique)
        alternations = sum(1 for i in range(1, len(tools)) if tools[i] != tools[i-1])
        return alternations >= 3 and len(tools) >= 4
