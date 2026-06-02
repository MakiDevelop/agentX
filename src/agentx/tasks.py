from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentx.task import TaskState


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
    MT22 遷移函式（v0.3.0 過渡期）。

    將舊的單一任務系統（.agentx/task.json）安全地遷移到新多任務清單（.agentx/tasks.json）。

    行為與守衛：
    - 只有在「新 tasks.json 不存在」且「舊 task.json 存在且為 active 任務」時才執行。
    - 這是保守策略，避免覆蓋使用者已開始使用的新任務。
    - 遷移成功後會把舊檔備份為 task.json.bak.*（策略 B）。
    - 後續啟動若已存在 tasks.json，則永遠不會再從舊檔遷移。

    這是為了讓使用者能平穩從舊系統過渡到新系統。
    回傳 True 表示本次執行了遷移。
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
        "notes": (
            "[自動遷移自舊單一任務系統]\n"
            f"原始標題：{title}\n"
            f"原始建立時間：{data.get('created_at', '未知')}"
        ),
    }
    save_tasks(workspace, [new_task])

    # === 務實策略（B）===
    # 遷移成功後把舊檔備份，而不是直接刪除。
    # 採用時間戳命名，確保永遠不會覆蓋既有備份。
    _backup_old_single_task_file(workspace, old_path)

    return True


def has_legacy_single_task(workspace: Path) -> bool:
    """檢查是否還存在舊的單一任務資料（MT22 過渡期工具）。
    Deprecated: 僅供 get_task_migration_status 診斷使用。cli 顯示分支已移除。
    未來版本將移除此函式。
    """
    return single_task_path(workspace).exists()


def get_task_migration_status(workspace: Path) -> dict:
    """
    MT22 過渡期工具：回報目前任務系統的遷移狀態。
    主要用於診斷與除錯。
    """
    has_old = has_legacy_single_task(workspace)
    has_new = tasks_path(workspace).exists()
    current_tasks = load_tasks(workspace)

    return {
        "has_legacy_single_task": has_old,
        "has_multi_task_file": has_new,
        "multi_task_count": len(current_tasks),
        "legacy_system_active": has_old and not has_new,
    }


def _backup_old_single_task_file(workspace: Path, old_path: Path) -> None:
    """MT22 備份策略（B）。

    將舊的單一任務檔安全地備份為帶時間戳的 .bak 檔。
    如果備份失敗，至少會嘗試刪除舊檔，避免它繼續被誤用。
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = workspace / ".agentx" / f"task.json.bak.{timestamp}"
        old_path.rename(backup_path)
    except Exception:
        # 備份失敗時，盡力刪除舊檔（避免後續流程誤讀）
        try:
            old_path.unlink()
        except Exception:
            pass


def _normalize_legacy_date(date_str: str) -> str:
    """MT22 過渡期日期正規化（A1-1f 逐一強化）。

    使用穩健的 regex 快速判斷是否像常見的舊日期格式。
    如果是，就保留原始字串（保留歷史資訊）。
    否則清空。這比嚴格解析在真實 legacy 資料上更可靠。
    """
    if not date_str or not isinstance(date_str, str):
        return ""

    s = date_str.strip()
    if not s:
        return ""

    # 基本 ISO-like 結構（支援 T 或空格分隔）
    # 符合就保留原始字串（務實容忍歷史格式）；否則直接清空。
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", s):
        return date_str.strip()

    return ""


def _get_legacy_task_if_exists(workspace: Path) -> "TaskState | None":
    """MT22 過渡期 helper（已 deprecated）。

    安全地嘗試讀取舊的單一任務系統（如果還存在）。
    只有在檔案存在、內容可解析、且有意義的任務資料時才回傳 TaskState。
    否則一律回傳 None，讓呼叫端優先使用新多任務清單。

    防禦性設計：
    - 檔案不存在 → None
    - 檔案過大（> 1MB）→ None（避免惡意或異常檔案）
    - 解析失敗 → None
    - 沒有有效 title → None

    Deprecated: cli 呼叫已移除。僅剩 doctor 遷移診斷使用。
    當舊系統完全退場後，此函式與相關 helper 可移除。
    """
    from .task import load_task

    legacy_path = workspace / ".agentx" / "task.json"
    if not legacy_path.exists():
        return None

    # 簡單的大小防禦，避免讀取異常大的檔案
    try:
        if legacy_path.stat().st_size > 1 * 1024 * 1024:  # 1MB
            return None
    except OSError:
        return None

    try:
        task = load_task(workspace)
    except Exception:
        # 任何解析或讀取異常都視為無效
        return None

    # 基本有效性檢查 + 資料品質正規化（MT22 過渡期）
    if not isinstance(task.title, str) or not task.title.strip():
        return None

    # 對舊資料做輕量清理（舊 TaskState 沒有 notes 欄位）
    cleaned_title = task.title.strip()[:200]

    # 移除控制字元與不可見字元（提升過渡期資料品質）
    cleaned_title = ''.join(
        ch for ch in cleaned_title 
        if ch.isprintable() or ch in ('\n', '\t')
    )

    # 進一步激進清理（A1-1d）：移除 emoji、特殊符號、連續空白
    import re
    # 移除常見 emoji 與零寬字元
    cleaned_title = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u200B-\u200D\uFEFF]',
        '',
        cleaned_title
    )
    # 最後再收斂空白
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()

    # 移除前後常見無意義標點（舊任務標題常見）
    cleaned_title = re.sub(r'^[\s\-\:\.\,\!\?\(\)\[\]【】「」『』“”‘’]+|[\s\-\:\.\,\!\?\(\)\[\]【】「」『』“”‘’]+$', '', cleaned_title).strip()

    # 移除常見前置編號/ID（舊任務標題常見 "123 - " 或 "BUG-456: "）
    cleaned_title = re.sub(r'^[\d\-:\s]+|^\w+-\d+[:\s]+', '', cleaned_title).strip()

    # 移除常見 TODO/FIXME 等前綴（舊任務標題非常常見）—— A1-1k 逐一強化
    cleaned_title = re.sub(r'^(TODO|FIXME|BUG|FEATURE|HACK|XXX)[:\-\s]*', '', cleaned_title, flags=re.IGNORECASE).strip()

    # status 標準化 + 輕量修復（舊→新系統）—— A1-1e 逐一強化
    raw_status = (task.status or "").strip().lower()
    status_map = {
        "active": "in_progress",
        "進行中": "in_progress",
        "進行": "in_progress",
        "in progress": "in_progress",
        "ongoing": "in_progress",
        "in_progress": "in_progress",
        "done": "done",
        "已完成": "done",
        "完成": "done",
        "finished": "done",
        "pending": "pending",
        "待辦": "pending",
        "todo": "pending",
        "未開始": "pending",
    }
    status = status_map.get(raw_status, raw_status)
    if status not in ("in_progress", "done", "pending"):
        status = ""

    # 最終整體品質守衛（A1-1l 逐一強化）
    # 如果清理後 title 極短 + status 無法有效映射，直接拒絕
    # 避免把「幾乎空殼」的舊單一任務也硬塞進新多任務清單
    if len(cleaned_title) < 3:
        return None
    if status == "" and len(cleaned_title) < 5:
        return None

    # 額外強化：如果 title 清理後只剩下數字或符號，也視為無意義
    if re.match(r'^[\d\s\-\:\.\,\!\?\(\)\[\]【】「」『』“”‘’]+$', cleaned_title):
        return None

    # 重新組裝一個乾淨的 TaskState（舊系統只有這四個欄位）
    cleaned_task = TaskState(
        title=cleaned_title,
        status=status,
        created_at=_normalize_legacy_date(task.created_at),
        updated_at=_normalize_legacy_date(task.updated_at),
    )

    # A1-1f 逐一強化：當真的走 legacy 路徑時，把原始資料記錄到 notes 供追溯
    original_title = getattr(task, 'title', '') or ''
    original_status = getattr(task, 'status', '') or ''
    if original_title or original_status:
        cleaned_task.notes = f"[來自舊單一任務] 原始標題：{original_title} | 原始狀態：{original_status}"

    return cleaned_task
