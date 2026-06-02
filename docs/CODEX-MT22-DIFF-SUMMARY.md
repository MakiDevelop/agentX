# MT22 Phase A 精簡 Diff 摘要（供 Codex 快速審查）

**Commit**：`fcd484a`  
**目的**：讓 Codex 能在 2-3 分鐘內掌握本次雙任務統一的實際程式碼變更，不必讀完整 380 行 diff。

---

## 1. 變更總覽（6 個檔案）

| 檔案 | 行數變化 | 性質 |
|------|----------|------|
| `src/agentx/tasks.py` | +51 | **新增核心**：遷移函數 |
| `src/agentx/cli.py` | +93 / -25 | **重構重點**：啟動遷移 + `/task` handler 全面改寫 |
| `src/agentx/task.py` | +7 | 文件：deprecation notice |
| `tests/test_tasks.py` | +40 | 新增 2 個遷移測試 |
| `docs/OPTIMIZATION_ROADMAP.md` | +168 | 新文件（非程式碼） |
| `docs/HEADLESS_OPTIMIZATION_LIST.md` | +22 | 追蹤更新 |

---

## 2. 最關鍵的三個程式碼區塊（請優先看這三處）

### (1) 遷移函數（tasks.py 新增）

```python
def migrate_single_task_if_needed(workspace: Path) -> bool:
    multi = load_tasks(workspace)
    if multi:
        return False                    # 已有新系統就不動

    old_path = single_task_path(workspace)
    if not old_path.exists():
        return False

    data = json.loads(...)              # 讀舊 task.json
    title = (data.get("title") or "").strip()
    if not title or data.get("status") != "active":
        return False                    # 只遷移進行中的

    new_task = {
        "id": 1,
        "description": title[:200],
        "status": "in_progress",
        "notes": f"[自動遷移自舊單一任務] created_at=..."
    }
    save_tasks(workspace, [new_task])
    return True
```

**Codex 請特別注意**：
- 只在 `multi` 為空時才遷移（防重複）。
- 只遷移 `status == "active"`。
- 永不刪除舊檔（單向遷移）。

---

### (2) 啟動時呼叫點（cli.py，兩個地方幾乎相同）

**Headless 路徑**（`run_print_prompt`）：
```python
project_config = ...
namespace = ...
migrate_single_task_if_needed(settings.workspace)   # ← 新增
ollama, _, tools = build_runtime(settings)
```

**互動式 shell 路徑**（`shell` 函數）：
```python
project_config = ...
mode = ...
migrate_single_task_if_needed(settings.workspace)   # ← 新增
...
agent_session = AgentSession(...)
```

**位置極早**，保證 `AgentSession` 初始化時已經看到正確的多任務清單。

---

### (3) `/task` handler 完整重寫（cli.py 最大區塊）

舊版（~15 行）：
```python
if prompt == "/task":
    task = load_task(...)          # 舊單一任務
    print_task(task)
    continue

if prompt.startswith("/task "):
    value = ...
    if value == "done":
        task = finish_task(...)
    elif ...
    else:
        task = start_task(..., value)
    print_task(task)
```

新版（~85 行，核心邏輯）：
```python
if prompt == "/task" or prompt.startswith("/task "):
    tasks = load_tasks(settings.workspace)          # ← 全部走新系統

    if not value or value in ("status", "list"):
        summary = format_task_list_summary(tasks)   # 與 headless 共用同一格式化函數
        console.print(Panel(summary...))
        return

    if value.startswith("add "):
        ... append + save_tasks ...

    if value.startswith("update "):
        tid = int(...)
        for t in tasks:
            if t["id"] == tid:
                t["status"] = ...
                t["notes"] = ...
        save_tasks(...)

    if value.startswith("done "):
        ...

    if value == "clear":
        save_tasks(workspace, [])

    # 相容舊語法：/task 重構認證模組
    if value and not value.startswith(("add","update","done","clear")):
        tasks.append({"id": get_next..., "status": "in_progress", ...})
        save_tasks(...)
```

**Codex 請特別注意**：
- 完全使用 `load_tasks` / `save_tasks` / `format_task_list_summary`（與 AgentSession 一致）。
- 對弱模型的錯誤處理（例如 `task id 必須是數字`）。
- 舊語法相容層的存在。

---

## 3. 其他小變更（可快速略過）

- `task.py` 只加了 7 行 deprecation 文字說明，無邏輯改變。
- `test_tasks.py` 新增兩個測試：
  - `test_migrate_single_task_creates_multi_task`
  - `test_migrate_does_nothing_if_multi_already_exists`
- 兩份文件更新（roadmap + progress tracking）。

---

## 4. 建議 Codex 審查順序（最高效率）

1. 先看上面 **(1) 遷移函數**（判斷策略是否安全）
2. 再看 **(2) 兩個啟動呼叫點**（確認時機正確）
3. 重點看 **(3) 新 `/task` handler** 的 parser 與邊界處理
4. 最後看 `test_migrate_*` 是否真的覆蓋到關鍵 case
5. 再回頭看 briefing 裡的 7 個風險問題，確認程式碼是否真的解決或規避了那些風險。

---

**結語**：

這份摘要只保留「必須讓 Codex 親眼看到」的三個核心程式碼區塊 + 必要上下文。  
搭配 `docs/CODEX-REVIEW-MT22-Dual-Task-Unification.md` 使用效果最佳。

需要我再產出「單一函數極簡版」（只剩 migrate + handler 核心 40 行）嗎？還是這個長度已經適合直接餵 Codex？