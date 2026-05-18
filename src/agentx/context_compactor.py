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


class HeuristicContextCompactor(ContextCompactor):
    """
    目前預設的強啟發式壓縮器（Context Compaction v2）。

    改進重點（相較舊版）：
    - 強制帶入當前多任務清單摘要（來自 tasks.py）
    - 優先保留 Reflection、STUCK 介入、成功編輯結果
    - 結構化輸出區塊，更容易讓後續模型理解
    - 保留最後 keep_last 則原始訊息作為連續性
    """

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

        # 1. 找出 bootstrap（前幾則 system 訊息，包含 repo + memory context）
        bootstrap: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system" and len(bootstrap) < 3:
                bootstrap.append(m)
            else:
                rest.append(m)

        # 2. 決定要保留的尾巴
        tail = rest[-keep_last:] if len(rest) > keep_last else rest

        # 3. 收集重要片段
        reflections: list[str] = []
        important_actions: list[str] = []
        recent_user: list[str] = []

        for m in rest:
            role = m.get("role")
            content = str(m.get("content", ""))

            if "=== Reflection" in content or "Reflection" in content:
                reflections.append(content.replace("\n", " ")[:400])
            elif role == "user":
                recent_user.append(content.replace("\n", " ")[:350])
            elif role == "tool" and ("成功" in content or "edit" in content.lower() or "search_replace" in content):
                important_actions.append(content.replace("\n", " ")[:300])

        # 4. 建構新的摘要 system message
        summary_lines: list[str] = [
            "【Session 已壓縮 - Context Compaction v2】",
            f"原始訊息數：{len(messages)}，保留最近 {len(tail)} 則 + 結構化摘要",
            "",
        ]

        # 任務狀態（Phase A 整合，極重要）
        task_summary = format_task_list_summary(tasks) if tasks else "目前沒有進行中的任務。"
        summary_lines.extend(["【目前任務清單】", task_summary, ""])

        if recent_user:
            summary_lines.append("【近期使用者目標】")
            for u in recent_user[-4:]:
                summary_lines.append(f"- {u}")
            summary_lines.append("")

        if reflections:
            summary_lines.append("【重要 Reflection / 決策】")
            for r in reflections[-3:]:
                summary_lines.append(f"- {r}")
            summary_lines.append("")

        if important_actions:
            summary_lines.append("【近期重要動作結果】")
            for a in important_actions[-3:]:
                summary_lines.append(f"- {a}")
            summary_lines.append("")

        summary_lines.append("【最近原始訊息（保留連續性）】")
        for m in tail:
            role = m.get("role", "unknown")
            c = str(m.get("content", "")).replace("\n", " ")[:280]
            summary_lines.append(f"[{role}] {c}")

        summary_lines.append("")
        summary_lines.append("請基於以上摘要繼續工作。必要時可要求更多細節。")

        compacted_summary = "\n".join(summary_lines)

        new_messages = [
            *bootstrap,
            {"role": "system", "content": compacted_summary},
            *tail,
        ]

        result_msg = (
            f"已執行 Context Compaction v2："
            f"從 {len(messages)} 則壓縮至約 {len(new_messages)} 則，"
            f"強制保留任務清單與關鍵決策。"
        )

        return new_messages, result_msg
