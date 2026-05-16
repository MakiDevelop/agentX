#!/usr/bin/env python3
"""
真實 Headless Task List 持久化驗證腳本 (Micro-task 21)

用法：
    uv run python scripts/verify_task_list_persistence.py

這個腳本會：
1. 清理舊的 tasks.json
2. 模擬第一次 headless session，建立 5 個任務
3. 模擬中斷
4. 建立第二次 headless session，檢查任務是否自動載入
5. 印出結果供人工確認
"""

from pathlib import Path
import shutil

from agentx.config import Settings
from agentx.loop import AgentSession
from agentx.ollama import OllamaClient
from agentx.tools import ToolRegistry


def main():
    import tempfile

    print("=" * 60)
    print("Micro-task 21 - Task List 持久化真實驗證（使用暫存目錄，安全）")
    print("=" * 60)

    # 使用暫存目錄，完全不碰真實 repo 的 .agentx/tasks.json
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)

        print(f"\n[1] 使用暫存 workspace: {workspace}")
        print("    （完全不會影響你真實的任務資料）")

        # 2. 模擬第一次 headless 建立任務
        print("\n[2] 第一次 headless session（模擬）...")
        from agentx.tasks import load_tasks, save_tasks, get_next_task_id

        tasks = []
        tasks.append({
            "id": get_next_task_id(tasks),
            "description": "分析 agentX 的 Task List 持久化機制",
            "status": "in_progress",
            "notes": "已讀取 tasks.py 與 loop.py"
        })
        tasks.append({
            "id": get_next_task_id(tasks),
            "description": "建立真實驗證腳本",
            "status": "done",
            "notes": "scripts/verify_task_list_persistence.py 已完成"
        })
        tasks.append({
            "id": get_next_task_id(tasks),
            "description": "在 docs/HEADLESS_OPTIMIZATION_LIST.md 記錄進度",
            "status": "pending",
            "notes": ""
        })
        tasks.append({
            "id": get_next_task_id(tasks),
            "description": "準備 Phase B prompt 注入實作",
            "status": "pending",
            "notes": ""
        })
        tasks.append({
            "id": get_next_task_id(tasks),
            "description": "執行 Codex review",
            "status": "pending",
            "notes": ""
        })

        save_tasks(workspace, tasks)
        print("   → 已建立 5 個任務並持久化")

        # 3. 模擬中斷
        print("\n[3] 第一次 headless session 結束（模擬中斷）")

        # 4. 第二次 headless 重新載入
        print("\n[4] 第二次 headless session（模擬重新載入）...")
        loaded = load_tasks(workspace)

        print(f"\n   載入結果：共 {len(loaded)} 個任務")
        for t in loaded:
            status_icon = "✅" if t["status"] == "done" else "⏳" if t["status"] == "in_progress" else "○"
            print(f"   {status_icon} [{t['id']}] {t['description']} ({t['status']})")

        # 5. 驗證
        print("\n" + "=" * 60)
        if len(loaded) == 5:
            print("✅ 驗證成功！持久化機制正常運作")
        else:
            print("❌ 驗證失敗")

    print("=" * 60)
    print("\n此腳本使用暫存目錄，安全無虞。")
    print("實際 headless 長任務驗證請直接用 gemma4:31b 跑。")


if __name__ == "__main__":
    main()
