from __future__ import annotations

from typing import Any

from agentx.errors import ErrorContext, ErrorType, RecoveryAction, RecoverySuggestion


class RecoveryPlaybook:
    """
    錯誤恢復策略 Playbook（Phase B2 成熟化版本）。

    目標：
    - 把原本散落在 loop.py 的經驗法則，變成可維護、可擴充的策略表。
    - 根據 ErrorType + 錯誤歷史模式，產生更具體、有優先序的恢復建議。
    - 為未來「輕量 LLM 輔助決策」或「規則引擎」預留介面。
    """

    def generate_suggestions(
        self,
        error_ctx: ErrorContext,
        error_history: list[ErrorContext],
        tasks: list[dict[str, Any]] | None = None,
    ) -> list[RecoverySuggestion]:
        """
        根據當前錯誤與歷史，產生有序的恢復建議（最多 3 個，由高信心到低）。
        """
        suggestions: list[RecoverySuggestion] = []
        recent = error_history[-6:] if error_history else []

        same_tool_count = sum(1 for e in recent if e.tool_name == error_ctx.tool_name)
        same_type_count = sum(1 for e in recent if e.error_type == error_ctx.error_type)
        total_errors = len(error_history)

        # === 優先級 1：明顯卡住（同工具 + 同類型多次失敗）===
        if same_tool_count >= 3 and same_type_count >= 3:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.BACKTRACK,
                description=f"強烈建議回退最近對 `{error_ctx.tool_name}` 的修改，檢查是否有引入破壞性變更。",
                rationale="同一個工具連續 3 次以上相同錯誤，通常是最後幾次編輯造成的。",
                confidence=0.85,
            ))
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.SIMPLIFY_SCOPE,
                description="把目前任務拆成更小的子任務，先完成其中一個再處理這個錯誤點。",
                rationale="複雜修改一次做太多很容易卡住，拆小步驟比較容易定位問題。",
                confidence=0.75,
            ))

        # === 優先級 2：執行錯誤為主 → 建議改變策略 ===
        if error_ctx.error_type == ErrorType.EXECUTION_ERROR:
            if same_tool_count >= 2:
                suggestions.append(RecoverySuggestion(
                    action=RecoveryAction.CHANGE_STRATEGY,
                    description="目前直接用 search_replace / insert_code 修改似乎不順，建議先寫測試、或先用 read_file 更精確掌握現況再改。",
                    rationale="執行錯誤連續發生時，直接盲改容易進入試錯迴圈。",
                    confidence=0.78,
                ))

            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.VERIFY_ASSUMPTION,
                description="先暫停修改，針對你目前最不確定的假設（例如某個函式行為、相依性版本），寫一個最小驗證腳本或查詢確認。",
                rationale="很多執行錯誤來自錯誤假設，先驗證假設比繼續修改更有效。",
                confidence=0.72,
            ))

        # === 優先級 3：暫時性錯誤 ===
        if error_ctx.error_type == ErrorType.TRANSIENT:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.RETRY_WITH_FIX,
                description="這看起來是暫時性問題（超時、連線、鎖定）。建議稍等 2-3 秒後重試，或稍微調整參數（例如 timeout 設大一點）。",
                rationale="暫時性錯誤通常不是邏輯問題，重試或微調參數通常就能過。",
                confidence=0.65,
            ))

        # === 優先級 4：呼叫錯誤 ===
        if error_ctx.error_type == ErrorType.CALL_ERROR:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.RETRY_WITH_FIX,
                description=f"這是呼叫層錯誤（參數、路徑、工具不存在）。請先用 list_files / read_file 確認實際狀態，再修正呼叫參數。",
                rationale="呼叫錯誤幾乎都是「模型對當前檔案系統狀態的認知與實際不符」造成的。",
                confidence=0.80,
            ))

        # === 優先級 5：長時間卡住 → 升級建議 ===
        if total_errors >= 7:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.ESCALATE_TO_USER,
                description="系統已多次嘗試各種恢復方式仍未成功。建議現在輸出 reflect，把目前任務狀態、錯誤歷史、已嘗試過的策略整理清楚後請求人類協助。",
                rationale="超過 7 次錯誤且多次恢復失敗時，人類介入通常是最快的方式。",
                confidence=0.92,
            ))

        # === 保底建議 ===
        if not suggestions:
            suggestions.append(RecoverySuggestion(
                action=RecoveryAction.REFLECT_AND_ADJUST,
                description="請進行一次結構化的錯誤 Reflection，清楚回答：這個錯誤的根本原因、屬於哪一類、你接下來打算改變什麼策略。",
                rationale="沒有明顯模式時，誠實 Reflection 是最安全的下一步。",
                confidence=0.55,
            ))

        # 只保留前 3 個最高信心的建議
        return sorted(suggestions, key=lambda s: s.confidence, reverse=True)[:3]
