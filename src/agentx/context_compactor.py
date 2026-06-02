from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agentx.tasks import format_task_list_summary


class ContextCompactor(ABC):
    """
    上下文壓縮器抽象介面。

    目標：
    - 讓 AgentSession 的 compact() 可以輕鬆替換不同策略（純啟發式 / LLM 輔助）。
    - 每次壓縮都要盡量保留「對後續工作真正重要」的資訊：
      * 目前任務清單（Phase A 成果）
      * 重要決策、Reflection、重試策略
      * 最近的成功動作與失敗
    """

    @abstractmethod
    def compact(
        self,
        messages: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        *,
        keep_last: int = 6,
        error_history: list[Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        執行壓縮。

        Returns:
            (new_messages, human_readable_summary)
        """
        raise NotImplementedError

    # 子類可 override 的設定
    max_summary_chars: int = 2400


class HeuristicContextCompactor(ContextCompactor):
    """
    目前預設的強啟發式壓縮器（Context Compaction v2）。

    穩定性強化重點（2026-05 打磨）：
    - 絕對保留前 2-3 則 bootstrap（repo context + memory context）
    - 強制把「目前任務清單」放在摘要最前面
    - 有 max_summary_chars 保護，避免摘要本身過長
    - 更聰明地挑選高價值訊息（Reflection、編輯成功、STUCK 恢復）
    - 支援重複壓縮也不會劣化
    """

    def __init__(self, max_summary_chars: int = 2400):
        self.max_summary_chars = max_summary_chars

    def compact(
        self,
        messages: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        *,
        keep_last: int = 6,
        error_history: list[Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        if not messages:
            return messages, "沒有可壓縮的上下文。"

        # 1. 強制保留 bootstrap（前 3 則 system 訊息通常是 repo + memory + 初始指令）
        bootstrap: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system" and len(bootstrap) < 3:
                bootstrap.append(m)
            else:
                rest.append(m)

        # 2. 保留尾巴（最近的原始對話）
        tail = rest[-keep_last:] if len(rest) > keep_last else rest

        # 3. 更聰明地收集高價值片段
        high_value: list[str] = []
        recent_user_goals: list[str] = []

        for m in rest:
            role = m.get("role")
            content = str(m.get("content", ""))

            # 高價值訊息標記（針對 Gemma4 等弱模型優化：多保留成功驗證、錯誤恢復、任務進度）
            is_high_value = any(marker in content for marker in [
                "=== Reflection", "Reflection Loop Guard", "STUCK", "已更新任務",
                "search_replace 成功", "insert_code 成功", "edit_file", "write_file", "patch applied",
                "編輯後", "下一步建議", "build_pass", "verified", "工具執行成功", "test passed",
                "目標達成", "micro-step complete", "verification"
            ])

            if is_high_value:
                high_value.append(content.replace("\n", " ")[:380])
            elif role == "user":
                recent_user_goals.append(content.replace("\n", " ")[:320])

        # 4. 建構受保護長度的摘要
        summary_lines: list[str] = [
            "【Session 已壓縮 - Context Compaction v2】",
            f"原始 {len(messages)} 則 → 保留 bootstrap + 結構化摘要 + 最近 {len(tail)} 則",
            "",
        ]

        # 任務清單永遠放在最前面（這是穩定性的核心）
        task_summary = format_task_list_summary(tasks) if tasks else "目前沒有進行中的任務。"
        summary_lines.extend(["【目前任務清單（最重要）】", task_summary, ""])

        if recent_user_goals:
            summary_lines.append("【近期主要目標】")
            for goal in recent_user_goals[-3:]:
                summary_lines.append(f"- {goal}")
            summary_lines.append("")

        if high_value:
            summary_lines.append("【關鍵決策 / Reflection / 重要動作】")
            for item in high_value[-4:]:
                summary_lines.append(f"- {item}")
            summary_lines.append("")

        summary_lines.append("【最近原始訊息（保持連續性）】")
        for m in tail:
            role = m.get("role", "unknown")
            c = str(m.get("content", "")).replace("\n", " ")[:260]
            summary_lines.append(f"[{role}] {c}")

        summary_lines.append("")
        summary_lines.append("以上為壓縮後的結構化上下文，請據此繼續執行。")

        compacted_summary = "\n".join(summary_lines)

        # 長度保護（避免摘要本身爆 token）
        if len(compacted_summary) > self.max_summary_chars:
            compacted_summary = compacted_summary[: self.max_summary_chars - 50] + "\n...（摘要已截斷）"

        new_messages = [
            *bootstrap,
            {"role": "system", "content": compacted_summary},
            *tail,
        ]

        result_msg = (
            f"已執行 Context Compaction v2："
            f"{len(messages)} → {len(new_messages)} 則，"
            f"任務清單與關鍵決策已保留。"
        )

        return new_messages, result_msg
