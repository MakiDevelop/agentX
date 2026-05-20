# MT22 Legacy Fallback Call Sites — Removal Readiness Checklist

**目的**：讓三處受控的 legacy 顯示分支從「已統一」進化到「可安全移除」的明確狀態，作為 v0.3.0 Release Gate 的具體佐證。

**原則**：
- 只有當「移除後不會影響任何使用者路徑 + 測試可證明」時才移除。
- 每個呼叫點必須有獨立的、可驗證的移除條件。
- 移除時必須同步刪除相關 helper（`_format_legacy_task_note`、`has_legacy_single_task` 在該路徑的用途等）。

**目前狀態（2026-05）**：三處已完成檢查模式統一 + TODO 標註 + 診斷工具，但尚未有系統化的移除條件清單。

---

## 1. `print_config`（src/agentx/cli.py）

**位置**：`print_config()` 函式內，約 line 428-436

**目前邏輯**：
```python
else:
    if has_legacy_single_task(settings.workspace):
        ... 顯示 legacy 資訊
        table.add_row("注意 (MT22)", _format_legacy_task_note())
        # TODO (v0.3.0+): 當舊系統完全退場後，此分支可移除
    else:
        table.add_row("tasks", "(none)")
```

**移除條件（必須全部滿足）**：
- [ ] `has_legacy_single_task()` 在整個 codebase 中不再被任何生產路徑呼叫（僅剩測試或診斷）。
- [ ] 所有現存的 `.agentx/task.json` 都已被遷移或明確標記為歷史備份（可透過 `get_task_migration_status` 驗證）。
- [ ] `test_config` 或相關 CLI 測試已移除對 legacy 分支的依賴，或明確標記為「legacy 歷史情境測試」。
- [ ] 使用者文件（Migration Guide）已說明舊系統已完全退場，不再需要此顯示。
- [ ] `/doctor` 輸出中已不再需要特別顯示 legacy 狀態（或已改為歷史記錄模式）。

**建議驗證測試（逐步補充中）**：
- `tests/test_tasks.py::test_migrate_single_task_creates_multi_task` 等系列（確認 legacy 建立與遷移行為）
- 未來可加入 `test_config` 中對 legacy 顯示的負面測試。

**移除後動作**：
- 刪除該 `if has_legacy_single_task` 分支。
- 移除對 `_format_legacy_task_note()` 的呼叫（若無其他用途）。
- 更新 `print_config` 的測試。

**風險若過早移除**：使用者若仍有未遷移的舊 `task.json`，會在 `/config` 看到不一致的狀態（顯示 "tasks: (none)" 但實際有舊資料）。

---

## 2. `build_handoff`（src/agentx/cli.py）

**位置**：`build_handoff()` 內，約 line 635-646

**目前邏輯**：
```python
else:
    if has_legacy_single_task(settings.workspace):
        legacy = _get_legacy_task_if_exists(...)
        task_section = f"task（legacy）... \n{_format_legacy_task_note()}\n"
        # TODO (v0.3.0+)
    ...
```

**移除條件**：
- [ ] `_get_legacy_task_if_exists()` 已被標記為 deprecated 且只在極少數測試中使用。
- [ ] handoff 產出的內容已不再需要向後相容舊單一任務格式（新舊 handoff 格式已穩定）。
- [ ] 所有使用 `build_handoff` 的呼叫者（目前主要是內部）都已能依賴 `tasks` 參數或 `task_summary`。
- [ ] 遷移測試已涵蓋「有 legacy 時 handoff 的行為」且確認移除後行為正確。
- [ ] 相關文件已更新，不再提及 legacy handoff 顯示。

**移除後動作**：
- 刪除 legacy 分支。
- 簡化 `task_section` 組裝邏輯。
- 清理 `_format_legacy_task_note()` 的最後引用。

**風險**：舊環境下執行的 handoff 會失去對歷史任務的描述，影響極少數仍在使用舊資料的使用者。

**建議驗證測試（逐步補充中）**：
- 目前 handoff 相關測試（test_cli_dispatch 或類似）中對 legacy 分支的覆蓋較弱，建議新增明確的 `build_handoff` legacy 情境測試。
- 確認移除後，帶有舊資料的 workspace 產出的 handoff 內容不再包含 legacy 區塊。

---

## 3. 啟動流程（shell 啟動區塊）

**位置**：`cli.py` 中建立 `ShellState` 後，約 line 760-769

**目前邏輯**：
```python
if has_legacy_single_task(settings.workspace):
    legacy = _get_legacy_task_if_exists(...)
    if legacy:
        transcript.write("task_legacy", ...)
    print_raw("[MT22] 偵測到舊的單一任務系統資料。...")
```

**移除條件**：
- [ ] 啟動時的 legacy transcript 寫入與提示已不再有任何除錯或遷移追蹤價值（可由 `get_task_migration_status` 取代）。
- [ ] 所有新使用者已預設使用多任務清單，沒有「首次啟動看到舊資料」的常見情境。
- [ ] transcript 相關測試已移除或隔離對 `task_legacy` 的依賴。
- [ ] `has_legacy_single_task` 在啟動路徑的呼叫已無意義（診斷工具已足夠）。
- [ ] Migration Guide 已明確說明啟動時不再有過渡提示。

**移除後動作**：
- 刪除整個 `if has_legacy_single_task` 區塊（包含 transcript 寫入與 print_raw）。
- 確認 `transcript` 模組不再需要 `task_legacy` 類型。
- 移除相關的測試案例或明確標記為歷史情境。

**風險**：少數仍在舊環境的使用者會突然失去啟動時的提醒，可能增加困惑（但若已到移除階段，此風險應已可接受）。

**建議驗證測試（逐步補充中）**：
- 目前對啟動流程中 `task_legacy` transcript 寫入的測試覆蓋不足。
- 建議新增測試驗證：有 legacy 資料時啟動不再寫入 `task_legacy` transcript 且不印出過渡提示。

---

## 整體移除前置條件（跨三處共同）

- [ ] `has_legacy_single_task()` 與 `_get_legacy_task_if_exists()` 已被正式標記為內部 deprecated，只存在於 `_legacy` 測試模組中。
- [ ] `get_task_migration_status()` 已成為主要的（且足夠）診斷工具。
- [ ] `tests/test_task.py` 已明確標記為「僅用於歷史相容驗證」，且不再是主要測試套件的一部分。
- [ ] 已存在獨立的 `docs/MT22-Migration-Guide.md`，清楚說明舊系統的退場時間點與清理方式。
- [ ] 至少一次完整的「模擬完全無 legacy 環境」的端到端測試通過。

---

## 建議執行順序

1. 完成 `test_tasks.py` 的 fixture 清理（讓新系統測試真正獨立）。
2. 補齊 `test_doctor.py` 對各種遷移狀態的覆蓋。
3. 撰寫 `docs/MT22-Migration-Guide.md`（可從本清單反向推導）。
4. 針對三處逐一建立移除 PR（每次只移除一處 + 更新文件 + 測試）。
5. 最終在某個版本中刪除 `task.py` 整個模組 + 相關 helper。

---

**記錄時間**：2026-05  
**負責人**：Grok（自主推進中）  
**下次更新**：當有任何一處滿足 3 個以上移除條件時

**參考**：
- `docs/MT22-v0.3.0-Handover.md`（主 handoff）
- Codex Review 意見（2026-05 session）
