# agentX CLI Dispatch 重構交接文件

**日期**：2026-05-18（本 session 續作）  
**負責人**：Claude（目前對話）  
**目標分支**：main  
**最新 Commit**：`305aed5` + 本次增量（/memory 等）

---

## 一、目前專案目標

正在將 `cli.py` 內原本的長串 `if prompt == "/xxx"` 指令處理，逐步改造成：

- `ShellState`：集中管理 shell 狀態
- `SLASH_HANDLERS`：指令 dispatch 表
- `register_handler()`：註冊機制

目的是提升可維護性、降低圈複雜度，並為後續 Tool 抽象化（ToolRegistry）做準備。

---

## 二、已完成項目（截至目前）

### 基礎架構
- [x] 引入 `ShellState` dataclass
- [x] 建立 `SLASH_HANDLERS` dispatch 字典
- [x] 建立 `register_handler()` 函數
- [x] 在主輸入迴圈加入 dispatch 檢查邏輯（支援帶參數指令）

### 已遷移指令（已驗證通過，r uff clean + 結構檢查）
- `/status`（基礎 handler + register）
- `/memory`（第一個帶參數，prefix dispatch 支援）
- `/sessions`
- `/transcript`

### 基礎架構強化（本次）
- 新增 `_try_dispatch()` 支援 prefix match（`cmd + " "`），由長到短比對，避免誤配
- 兩個 dispatch 呼叫點統一改用 _try_dispatch
- handler 內優先使用 `state.xxx`（如 state.namespace, state.settings）

### 其他改動
- 保留舊的 if-elif 作為 fallback（過渡期間，逐步移除）
- 已移除 `/memory`、`/sessions`、`/transcript` 的舊 if 區塊

### Memory Hall 查詢結果（project:agentX handoff 類型）
- 透過 team-memhall MCP `search_entries` 查 "handoff" / "project:agentX" / "dispatch" / "agentX" 等關鍵字 → 無匹配結果（回傳 []）
- team-memhall 目前多為其他成員的 team-onboarding / wrap-up episode（namespace 偏 team shared）
- agentX 專案的 handoff 實際寫入路徑：`MemoryHallClient` 直接 POST 到 `http://100.122.171.74:9100/v1/memory/write`，namespace="project:agentX"（或 "agent:agentx"），type 依關鍵字自動 "handoff" / "note"
- 本份 handoff doc 目前僅存在於 git docs/ ，尚未 ingest 到 memhall（後續 wrap-up 時可補）
- 結論：project:agentX 的 handoff 類型紀錄在本次查詢中尚未出現，符合「新 session 尚未寫入」預期

---

## 三、設計決策與重要觀念

- 所有 handler 都定義在 `shell()` 函數內（利用 closure 存取 `state`、`transcript`、`chat_messages` 等變數）。
- handler 統一簽名：`def handle_xxx(state: ShellState, prompt: str)`
- 目前仍保留 `SLASH_COMMANDS` list（用於補完與 `/help` 顯示說明）。
- 帶參數的指令（如 `/memory xxx`）已可透過 prefix 匹配處理。

---

## 四、下一步優先順序（第一批剩餘指令）

**本 session 已完成**：`/memory` + `/sessions` + `/transcript`（含 prefix dispatch 基礎）

建議繼續依序遷移以下簡單指令（下一批）：

1. `/handoff`（可選參數，較複雜因呼叫 write_handoff）
2. `/resume`
3. `/files`
4. `/read`
5. `/search`
6. `/fetch`
7. `/git` / `/diff` / `/apply`（git 相關，可群組）

**複雜指令建議延後**：

**複雜指令建議延後**：
- `/task`（子命令多）
- `/config` 系列
- `/plan` + `/execute`
- `/commit` + `/review`
- `/docker` 系列
- `/run`

---

## 五、重要檔案位置

| 檔案 | 說明 |
|------|------|
| `src/agentx/cli.py` | 目前主要戰場，所有 dispatch 相關改動都在這裡 |
| `src/agentx/loop.py` | `AgentSession` 與 `state` 互動的地方 |
| `tests/test_cli_dispatch.py` | 未來應補強的測試檔案（目前尚未建立） |

---

## 六、測試與驗證方式

1. `uv run ruff check src/agentx/cli.py`
2. `ax` 啟動 shell
3. 逐一輸入已遷移的指令確認功能正常
4. 輸入未遷移的指令確認仍可正常使用（fallback 機制）

---

## 七、已知注意事項

- 目前 `state` 變數必須在任何指令處理之前就建立好。
- handler 內若需要修改 `chat_messages` 等外部變數，記得使用 `nonlocal`。
- `/task` 指令因為子命令複雜，建議最後再處理。
- 目前還沒有為 dispatch 寫單元測試，之後建議補上。

---

## 八、建議的下一個動作

1. 繼續逐一遷移下一批簡單指令（從 `/handoff` 開始）。
2. 每遷移 4~5 個指令就考慮 commit 一次（本次已做 3 個 + dispatch 強化）。
3. 後續可考慮把 `/clear`、`/doctor` 等舊 if 也抽出 handler（目前 doc 列為「已完成」但實際仍走 fallback）。
4. 等第一批全部完成後，再評估是否要處理 ToolRegistry 的部分。
5. 完成階段性 commit 後，依 §2 規則交由 Codex 審查本次 dispatch 改動。

---

## 九、聯絡與備註

- 這份文件同時會寫進：
  - `docs/CLI_DISPATCH_REFACTOR_HANDOFF.md`（Git）
  - Memory Hall（namespace: `project:agentX`）
  - 本地 session 目錄備份

有任何疑問或想調整方向，歡迎直接在下一個對話中引用本文件。
