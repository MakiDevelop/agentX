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
1. 升級到最新版本。
2. 正常使用 agentX（新任務一律走 `/task` 多任務清單）。
3. 觀察幾次啟動：
   - 如果有舊的進行中任務，會自動遷移並備份舊檔。
   - 啟動時會看到過渡提示。
4. 確認遷移成功後（可用 `agentx doctor` 檢查），可選擇性手動刪除歷史備份（`.agentx/task.json.bak.*`）。
5. 未來版本會提供更明確的清理提示與指令。

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

---

## 4. 貢獻者注意事項

- 任何新功能請優先使用新多任務 API。
- 測試中建立 legacy 狀態請使用 `tests/test_tasks.py` 中的 `_write_legacy_task` helper。
- 移除舊系統相關程式碼前，請先確認 `docs/MT22-Legacy-Removal-Checklist.md` 中的條件已滿足。

---

**最後更新**：2026-05  
**維護者**：Grok（自主推進中）

> 此文件為草稿骨架，內容將隨實際進度持續補充。
