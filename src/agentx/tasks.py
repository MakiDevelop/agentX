from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def tasks_path(workspace: Path) -> Path:
    """回傳多任務清單儲存路徑：.agentx/tasks.json"""
    return workspace / ".agentx" / "tasks.json"


def load_tasks(workspace: Path) -> list[dict[str, Any]]:
    """
    載入多任務清單。
    如果檔案不存在、損壞或格式錯誤，安全地回傳空列表。
    同時做最基本的 schema normalize（防呆），避免壞資料讓後續函數炸掉。
    """
    path = tasks_path(workspace)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []

        normalized = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                task = {
                    "id": int(item.get("id", 0)),
                    "description": str(item.get("description", ""))[:200],
                    "status": item.get("status", "pending"),
                    "notes": str(item.get("notes", ""))[:500],
                }
                if task["id"] > 0 and task["description"]:
                    normalized.append(task)
            except (ValueError, TypeError):
                continue
        return normalized

    except (json.JSONDecodeError, OSError):
        return []


def save_tasks(workspace: Path, tasks: list[dict[str, Any]]) -> None:
    """
    儲存多任務清單。
    會自動建立 .agentx/ 目錄。
    """
    path = tasks_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_next_task_id(tasks: list[dict[str, Any]]) -> int:
    """根據現有任務計算下一個可用的 id（從 1 開始）"""
    if not tasks:
        return 1
    max_id = max((t.get("id", 0) for t in tasks), default=0)
    return max_id + 1


def find_task(tasks: list[dict[str, Any]], task_id: int) -> dict[str, Any] | None:
    """根據 id 找出對應任務（找不到回傳 None）"""
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return None


def format_task_list_summary(tasks: list[dict[str, Any]], max_active: int = 8) -> str:
    """
    將多任務清單格式化成適合放入 headless system prompt 的摘要文字。
    目的：讓模型不用每次都呼叫 task_list，就能清楚知道目前在做什麼。

    只詳細顯示進行中 + 待辦任務（最多 max_active 個，優先顯示進行中），
    已完成任務只顯示數量。
    """
    if not tasks:
        return "目前沒有建立任何任務清單。"

    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    pending = [t for t in tasks if t.get("status") == "pending"]
    done_count = sum(1 for t in tasks if t.get("status") == "done")

    # 正確計算顯示數量：優先顯示 in_progress，剩餘名額給 pending
    remaining = max_active
    shown_in_progress = in_progress[:remaining]
    remaining = max(0, remaining - len(shown_in_progress))
    shown_pending = pending[:remaining]

    hidden_count = (len(in_progress) - len(shown_in_progress)) + (len(pending) - len(shown_pending))

    lines = ["【目前任務清單摘要】"]

    if shown_in_progress:
        lines.append("進行中：")
        for t in shown_in_progress:
            note = f"（{t.get('notes', '')[:40]}）" if t.get("notes") else ""
            lines.append(f"  - #{t['id']} {t['description']}{note}")

    if shown_pending:
        lines.append("待辦：")
        for t in shown_pending:
            note = f"（{t.get('notes', '')[:40]}）" if t.get("notes") else ""
            lines.append(f"  - #{t['id']} {t['description']}{note}")

    if hidden_count > 0:
        lines.append(f"  （還有 {hidden_count} 個待辦任務未列出）")

    if done_count > 0:
        lines.append(f"已完成：{done_count} 個")

    if not shown_in_progress and not shown_pending:
        lines.append("目前所有任務都已完成。")

    return "\n".join(lines)


# === 單任務 → 多任務清單 自動遷移（Phase A / MT22） ===

def single_task_path(workspace: Path) -> Path:
    """舊的單一任務檔案路徑（即將退場）"""
    return workspace / ".agentx" / "task.json"


def migrate_single_task_if_needed(workspace: Path) -> bool:
    """
    MT22 遷移函式：將舊的單一任務系統（task.json）遷移到新多任務清單。

    行為：
    - 只有在「新 tasks.json 不存在」且「舊 task.json 存在且為 active 任務」時才執行遷移。
    - 遷移成功後，會把舊的 task.json 改名為 task.json.bak（備份），避免重複遷移。
    - 這是務實路線：保留備份但不再使用舊系統。

    回傳：
    - True：成功執行遷移
    - False：無需遷移或遷移失敗
    """
    tasks_file = tasks_path(workspace)
    old_path = single_task_path(workspace)

    # 關鍵守衛：新系統已存在就不遷移（避免覆蓋）
    if tasks_file.exists():
        return False

    if not old_path.exists():
        return False

    try:
        data = json.loads(old_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    title = (data.get("title") or "").strip()
    status = data.get("status", "")
    if not title or status != "active":
        return False

    # 執行遷移
    new_task = {
        "id": 1,
        "description": title[:200],
        "status": "in_progress",
        "notes": f"[自動遷移自舊單一任務] created_at={data.get('created_at', '')}",
    }
    save_tasks(workspace, [new_task])

    # === 務實策略（B）===
    # 遷移成功後把舊檔改名備份，而不是直接刪除。
    # 這樣既安全，又讓舊檔不會再被後續流程誤用。
    try:
        backup_path = workspace / ".agentx" / "task.json.bak"
        if backup_path.exists():
            # 如果備份已存在，加上時間戳避免覆蓋
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = workspace / ".agentx" / f"task.json.bak.{timestamp}"
        old_path.rename(backup_path)
    except Exception:
        # 備份失敗不影響遷移結果，只記錄即可
        # 後續可以考慮加上 logging
        pass

    return True


def _get_legacy_task_if_exists(workspace: Path) -> "TaskState | None":
    """MT22 過渡期 helper。

    只在舊的 .agentx/task.json 仍然存在，且內容有意義時，才回傳舊的單一任務物件。
    否則回傳 None，讓呼叫端優先走新多任務清單。

    這是為了在過渡期間保留相容性，當舊系統完全退場後，此函式與其呼叫者可移除。
    """
    from .task import TaskState, load_task

    legacy_path = workspace / ".agentx" / "task.json"
    if not legacy_path.exists():
        return None

    task = load_task(workspace)
    if not task.title:
        return None
    return task

