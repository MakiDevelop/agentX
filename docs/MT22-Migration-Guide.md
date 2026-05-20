# MT22 Migration Guide（v0.3.0 過渡期）

**目標讀者**：agentX 使用者、貢獻者

**目的**：說明如何從舊單一任務系統平穩過渡到新多任務清單，並在 v0.3.0 之後安全移除舊系統。

---

## 1. 目前狀態（2026-05）

- 新多任務系統（`.agentx/tasks.json` + `agentx.tasks` API）已成為主要真相來源。
- 舊單一任務系統（`.agentx/task.json` + `agentx.task`）已進入受控過渡期，所有公開 API 均已標記 `DeprecationWarning`。
- 啟動時會自動嘗試遷移進行中的舊任務（策略 B：成功後備份為 `task.json.bak.*`）。
- 診斷工具：
  - `has_legacy_single_task(workspace)`
  - `get_task_migration_status(workspace)`
  - `/doctor` 會顯示當前狀態。

---

## 2. 對使用者的影響與建議

### 一般使用者
- 建議盡快改用 `/task` 相關指令管理多任務清單。
- 舊 `task.json` 若為進行中狀態，啟動時會自動遷移。
- 啟動時若偵測到舊資料，會看到過渡提示。

### 進階使用者 / 腳本作者
- 請改用 `load_tasks` / `save_tasks` / `task_add` 等新 API。
- 避免直接操作 `.agentx/task.json`。

### 移除時間點（預計）
- v0.3.0：舊系統處於「受控過渡 + 明確 deprecated」階段。
- v0.4+：預計完全移除 `task.py` 模組及相關相容層。

### 使用者遷移建議流程（推薦做法）

**步驟 1：升級並切換習慣**
- 升級到包含本次 MT22 改進的版本。
- 從現在開始，所有新任務一律使用 `/task` 多任務清單相關指令（不要再用舊的單一任務指令）。

**步驟 2：讓自動遷移自然發生**
- 正常啟動與使用 agentX。
- 如果 workspace 中有進行中的舊單一任務，啟動時會自動執行遷移，並把舊檔備份為 `task.json.bak.<timestamp>`。
- 啟動畫面會出現明確的過渡提示。

**步驟 3：驗證遷移結果**
```bash
agentx doctor
```
或在 Python 中：
```python
from agentx.tasks import get_task_migration_status
print(get_task_migration_status(Path(".")))
```
建議狀態：
- `has_legacy_single_task: false` 或 `legacy_system_active: false`
- `has_multi_task_file: true`
- 多任務清單中出現原本的任務

**步驟 4：選擇性清理歷史資料（可選）**
- 確認一切正常後，可手動刪除 `.agentx/task.json.bak.*` 歷史備份（建議先備份）。
- 未來版本會提供更明確的一鍵清理指令。

**步驟 5：持續觀察**
- 連續幾次啟動都沒有舊系統提示，即表示過渡完成。

## 3. 常見問題

**Q: 我的舊任務沒被遷移？**
A: 只有「active」狀態的舊任務會被自動遷移。已完成或無效的舊任務不會影響新系統。

**Q: 我還能手動建立舊 task.json 嗎？**
A: 可以，但強烈不建議。新系統啟動後不會再讀取它（除非你刻意觸發相容層）。

**Q: 如何檢查當前狀態？**
```bash
agentx doctor
# 或在 Python 中
from agentx.tasks import get_task_migration_status
print(get_task_migration_status(Path(".")))
```

**Q: 我想手動清理舊系統資料，該怎麼做？**
A: 
1. 確認目前狀態：`agentx doctor` 或使用 `get_task_migration_status`。
2. 如果舊任務已遷移，舊 `task.json` 會被備份為 `task.json.bak.*`。
3. 若想徹底移除歷史備份，可手動刪除 `.agentx/task.json.bak.*` 檔案（建議先備份）。
4. 未來版本將提供更明確的一鍵清理指令（規劃中）。

## 4. 貢獻者注意事項

### 移除舊系統前的準備清單

在提出移除 legacy 相關程式碼的 PR 前，請確認以下事項：

1. **測試覆蓋**
   - `tests/test_tasks.py` 中所有 legacy 建立都已改用 `_write_legacy_task`。
   - 執行 `pytest tests/test_tasks.py -k "migrate or legacy" -q` 全綠。
   - `tests/test_doctor.py` 中 migration 診斷測試已涵蓋主要情境（包含損壞檔、錯誤處理）。

2. **本地驗證**
   - 在帶有舊 `task.json` 的 workspace 啟動，確認：
     - 不再寫入 `task_legacy` transcript
     - 不再顯示過渡提示
     - `agentx doctor` 正確顯示 `legacy_only` / `mixed` 狀態
   - 檢查 `docs/MT22-Legacy-Removal-Checklist.md` 中三處呼叫點的移除條件是否都已滿足。

3. **文件同步**
   - 更新或確認 `docs/MT22-Migration-Guide.md` 已說明過渡完成後的使用者體驗。
   - 確認 Removal Checklist 中的驗證建議仍然準確。

完成以上檢查後再提交移除 PR。

### 一般貢獻原則
- 任何新功能請優先使用新多任務 API。
- 測試中建立 legacy 狀態請使用 `tests/test_tasks.py` 中的 `_write_legacy_task` helper。
- 移除舊系統相關程式碼前，請先確認 `docs/MT22-Legacy-Removal-Checklist.md` 中的條件已滿足。

## 5. 常見移除風險與緩解方式

移除舊系統時可能遇到的風險與建議緩解方式：

### 風險 1：舊環境使用者突然失去過渡提示
**現象**：仍在使用舊 `task.json` 的使用者，升級後不再看到任何提醒，可能困惑「我的任務去哪了？」

**緩解**：
- 在 v0.3.0 / v0.4 的 release notes 與 blog 清楚說明過渡完成。
- `agentx doctor` 持續保留對舊資料的診斷能力（即使不再顯示提示）。

---

## 6. 移除後的建議清理與注意事項

當舊系統完全移除後，建議執行以下清理：

### 1. 刪除歷史備份檔
```bash
rm -f .agentx/task.json.bak.*
```
建議先確認沒有重要歷史資料再刪除。

### 2. 清理測試中的 legacy 建立方式
- 所有測試應只使用 `_write_legacy_task`（若還需要模擬舊資料）。
- 移除或隔離 `tests/test_tasks.py` 中任何直接呼叫舊 API 的 legacy 建立程式碼。

### 3. 更新貢獻者文件
- 確認 `docs/MT22-Legacy-Removal-Checklist.md` 已標記為歷史文件（可加上「已完成」標記）。
- 在 README 或貢獻指南中移除任何提及舊單一任務系統的內容。

### 4. 長期觀察
- 建議在移除後的 1-2 個版本中，持續監控是否有使用者回報舊資料相關問題。
- `agentx doctor` 可保留對舊 `task.json` 的診斷能力一段時間（作為安全網）。

---

## 7. 移除後的常見使用者問題與對應處理

舊系統完全移除後，使用者可能會遇到的實際問題與建議處理方式：

### 舊的單一任務相關指令還能不能用？
- 舊的 `/task`、`/task start` 等單一任務指令將不再可用。
- 請改用新的多任務指令（`/task` 清單相關指令）。
- 系統會在第一次使用時給出明確提示。

### 我還能看到以前的舊任務記錄嗎？
- 舊的單一任務資料在移除後不會再出現在 `/config`、handoff、doctor 等地方。
- 如果你有備份 `.agentx/task.json.bak.*` 檔案，可以手動查看歷史內容。
- 建議在移除前確認是否需要保留這些歷史記錄。

### `agentx doctor` 還會顯示舊系統相關資訊嗎？
- 移除後，`agentx doctor` 將不再顯示 `task_migration (MT22)` 相關項目。
- 如果你還想檢查是否有殘留的舊資料，可以手動查看 `.agentx/` 目錄。

### 怎麼確認自己已經完全切換到新系統？
推薦檢查清單：
1. `agentx doctor` 不再出現任何與舊單一任務系統相關的輸出。
2. 啟動時不再有任何過渡提示。
3. 所有任務相關操作都使用新的多任務清單。
4. 沒有依賴 `task.py` 或 `TaskState` 的自訂腳本。

---

## 8. 移除後如何驗證自己是否已完全切換

移除舊系統後，建議用以下方式確認自己已經完全切換到新多任務系統：

### 推薦檢查清單
1. 執行 `agentx doctor`
   - 應該完全看不到 `task_migration (MT22)` 相關項目。
2. 正常啟動 agentX 幾次
   - 啟動時不應再出現任何過渡提示或 `[MT22]` 相關訊息。
3. 檢查 `.agentx/` 目錄
   - 不應存在活躍的 `task.json`（只有 `.bak.*` 歷史備份是正常的）。
4. 嘗試使用舊的單一任務相關指令（如果還記得的話）
   - 應該會得到明確的提示，引導使用新指令。
5. （進階）執行診斷
   ```python
   from agentx.tasks import get_task_migration_status
   print(get_task_migration_status(Path(".")))
   ```
   - `has_legacy_single_task` 應為 `false`
   - `legacy_system_active` 應為 `false`

完成以上檢查後，即可認為過渡已完成。

---

## 9. v1.0.0 之後的建議演進方向

移除舊系統後，建議後續可以考慮的方向（非 v1.0.0 必須）：

- 提供 `/task cleanup-legacy` 指令，幫助使用者一鍵清理歷史備份。
- 在 `agentx doctor` 中加入「legacy 殘留風險評分」。
- 將多任務系統的診斷能力進一步整合到 `/status` 與 TUI 狀態顯示中。
- 考慮在未來版本中移除所有相容層（包含 `_get_legacy_task_if_exists`）。

---

## 10. 移除後的團隊溝通建議

如果你的團隊正在推動舊系統退場，以下是一些實務建議：

- **提前溝通**：在移除 PR 合入前 1-2 週，在團隊會議或 Slack 提前告知「舊單一任務系統將在下個版本完全退場」。
- **提供過渡指引**：可以直接分享本文件的「使用者遷移建議流程」章節。
- **準備 fallback**：如果有人強烈反對，可以先讓 `agentx doctor` 繼續保留對舊資料的診斷能力一段時間，降低阻力。
- **紀錄決策**：建議在團隊 wiki 或 README 補上一小段說明「為什麼要移除舊系統」，方便後續新成員理解。

---

**最後更新**：2026-05  
**維護者**：Grok（自主推進中）

> 此文件將隨 v0.3.0 移除工作持續更新。
- 考慮在 1-2 個版本內保留極簡的「偵測到舊資料」靜默記錄（僅寫 transcript，不印出）。

### 風險 2：貢獻者誤刪除仍在使用的相容層
**現象**：某處還在依賴 `_get_legacy_task_if_exists` 或 `has_legacy_single_task`，但被誤移除導致功能壞掉。

**緩解**：
- 移除前必須通過 `docs/MT22-Legacy-Removal-Checklist.md` 的完整檢查。
- 使用 grep + 靜態分析確認無剩餘呼叫。
- 先把相容層函式標記為 `internal` + 加強文件，降低誤用風險。

### 風險 3：測試覆蓋不足導致回歸
**現象**：移除後某些邊界情境（損壞舊檔、並行讀寫等）未被測試覆蓋。

**緩解**：
- 移除 PR 必須附上「移除前後測試執行結果對比」。
- 保留一小組「legacy 歷史情境」的隔離測試（放在 `tests/test_tasks.py` 的 legacy 區塊），即使主流程已移除也保留驗證價值。

---

**最後更新**：2026-05  
**維護者**：Grok（自主推進中）

> 此文件為草稿，內容將隨實際移除進度持續補充與調整。

---

**最後更新**：2026-05  
**維護者**：Grok（自主推進中）

> 此文件為草稿骨架，內容將隨實際進度持續補充。
