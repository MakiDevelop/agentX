# MT22 Legacy Fallback Call Sites — Removal Readiness Checklist

**目的**：讓三處受控的 legacy 顯示分支從「已統一」進化到「可安全移除」的明確狀態，作為 v0.3.0 Release Gate 的具體佐證。

**原則**：
- 只有當「移除後不會影響任何使用者路徑 + 測試可證明」時才移除。
- 每個呼叫點必須有獨立的、可驗證的移除條件。
- 移除時必須同步刪除相關 helper（`_format_legacy_task_note`、`has_legacy_single_task` 在該路徑的用途等）。

**目前狀態（推進中）**：cli.py 三處 legacy if 分支已全部移除（print_config, build_handoff, 啟動流程）。TODO 標註已清理。helper 函式仍在 tasks.py 供 doctor 遷移狀態診斷使用。後續需確認無其他生產路徑呼叫 has_legacy_single_task 後，可進一步 deprecated 並移除。

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
- [x] cli.py print_config legacy 分支已移除。
- [ ] `has_legacy_single_task()` 在整個 codebase 中不再被任何生產路徑呼叫（僅剩測試或診斷）。（cli 呼叫已清，剩 doctor 內部 + tasks.py）
- [ ] 執行 `agentx doctor` 確認不再顯示 `task_migration (MT22)` 項目。
- [ ] 所有現存的 `.agentx/task.json` 都已被遷移或明確標記為歷史備份（可透過 `get_task_migration_status` 驗證）。
- [ ] `tests/test_cli_dispatch.py` 及相關測試已移除或隔離對 print_config legacy 分支的依賴。
- [ ] `docs/MT22-Migration-Guide.md` 已清楚說明舊系統已退場。
- [x] 移除後，在帶有舊 `task.json` 的 workspace 執行 `/config` 不會再顯示 legacy 資訊。

**建議驗證測試（逐步補充中）**：
- `tests/test_tasks.py` 中的所有 `_write_legacy_task` + migrate 系列測試（已全面替換舊 API，涵蓋 active/non-active、髒資料、日期處理等情境）
- `tests/test_doctor.py::test_check_task_migration_*`（驗證診斷工具能正確區分 legacy_only / mixed / multi_only）
- `tests/test_cli_dispatch.py` 中對 `/config` 的相關測試（需確認 legacy 分支不再被觸發）
- 建議新增：明確的負面測試，驗證移除後 `/config` 在仍有舊 `task.json` 時的行為（或確認舊檔已被忽略）

**移除後動作**：
- [x] 刪除該 `if has_legacy_single_task` 分支。
- [x] 移除對 `_format_legacy_task_note()` 的呼叫（函式已刪）。
- [ ] 更新 `print_config` 的測試。

**風險若過早移除**：使用者若仍有未遷移的舊 `task.json`，會在 `/config` 看到不一致的狀態（顯示 "tasks: (none)" 但實際有舊資料）。（已移除，風險由遷移狀態診斷控管）

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
- [x] cli.py build_handoff legacy 分支已移除。
- [ ] `_get_legacy_task_if_exists()` 已被標記為 deprecated 且只在極少數測試中使用。
- [ ] 執行帶有舊 `task.json` 的 workspace，確認 `build_handoff` 產出不再包含 legacy 區塊。（已移除）
- [ ] 所有使用 `build_handoff` 的呼叫者已能依賴 `tasks` 參數或 `task_summary`。
- [ ] `tests/test_tasks.py` 中的 migrate 系列測試 + `tests/test_doctor.py` 已涵蓋「有 legacy 時 handoff 的行為」。
- [ ] `docs/MT22-Migration-Guide.md` 已清楚說明舊系統已退場，不再需要在 handoff 中顯示 legacy 資訊。

**移除後動作**：
- [x] 刪除 legacy 分支。
- [x] 簡化 `task_section` 組裝邏輯。
- [x] 清理 `_format_legacy_task_note()` 的最後引用。

**風險**：舊環境下執行的 handoff 會失去對歷史任務的描述，影響極少數仍在使用舊資料的使用者。（已移除，風險由遷移診斷控管）

**建議驗證測試（逐步補充中）**：
- `tests/test_tasks.py` 中的 migrate 系列測試（已全面改用 `_write_legacy_task`，涵蓋各種 legacy 情境）
- `tests/test_doctor.py::test_check_task_migration_*`（驗證診斷工具能正確反映 handoff 會看到的狀態）
- 建議新增：明確的 `build_handoff` legacy 情境測試，驗證移除後帶有舊資料的 workspace 產出的 handoff 不再包含 legacy 區塊
- 確認 `test_cli_dispatch.py` 或相關測試中，legacy 分支在 `build_handoff` 路徑不再被觸發

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
- [x] cli.py 啟動流程 legacy if 已移除。
- [ ] 執行 `agentx doctor` 確認不再顯示 `task_migration (MT22)` 項目。
- [ ] 啟動帶有舊 `task.json` 的 workspace，確認完全沒有 `task_legacy` transcript 寫入與過渡提示。（已移除）
- [ ] transcript 相關測試已移除或隔離對 `task_legacy` 的依賴。
- [ ] `tests/test_tasks.py` + `tests/test_doctor.py` 已涵蓋啟動時 legacy 處理的主要情境。
- [ ] `docs/MT22-Migration-Guide.md` 已清楚說明啟動時不再有過渡提示。

**移除後動作**：
- [x] 刪除整個 `if has_legacy_single_task` 區塊（包含 transcript 寫入與 print_raw）。
- [ ] 確認 `transcript` 模組不再需要 `task_legacy` 類型。

**風險**：少數仍在舊環境的使用者會突然失去啟動時的提醒，可能增加困惑（但若已到移除階段，此風險應已可接受）。（已移除）

**建議驗證測試（逐步補充中）**：
- `tests/test_tasks.py` 中的 migrate 系列測試（驗證 legacy 資料在啟動時的處理邏輯）
- `tests/test_doctor.py::test_check_task_migration_*`（驗證診斷工具能正確反映啟動時的 legacy 狀態）
- 啟動流程相關測試（需確認 `task_legacy` transcript 寫入與過渡提示不再出現）
- 建議新增：明確測試，驗證移除後帶有舊 `task.json` 的 workspace 啟動時完全沒有 legacy 相關行為
- 額外建議：在 CI 中加入「無 legacy 環境」啟動測試，確保移除後不會有回歸

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

**記錄時間**：推進中  
**負責人**：Grok（逐一推進中）  
**更新**：cli.py 三處 legacy 分支已移除（2026 推進）。helper 仍存於 tasks.py 供診斷。下一步：確認無生產呼叫後標記 deprecated，更新 migration guide，清理剩餘 test_task.py 等。

**參考**：
- `docs/MT22-v0.3.0-Handover.md`（主 handoff）
- Codex Review 意見（2026-05 session）
