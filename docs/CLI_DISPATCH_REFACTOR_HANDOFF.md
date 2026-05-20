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

### Codex 審查結論（2026-05-18 ff46ffe 批次，review id 019e397e-3535...）
- **P1（唯一標記）**：`ShellState` 目前不是單一真相來源。
  - `plan_mode`、`mode`、`settings` 仍是 closure 變數。
  - `/plan`、`/mode`、`/model`、`/persona` 切換後沒有同步回 `state`，導致後續 handler 依賴 `state.*` 會看到 stale 值。
  - 影響範圍：`/status` 顯示錯誤 + 未來更多 handler 遷移。
  - Codex 建議：短期在變更點補 `state.plan_mode = ...` 等同步；中期把 shell runtime 狀態讀寫統一收斂到 `ShellState`。
- 其他觀察：prefix 匹配安全、lint/test 全過（96 passed）、底部 `/status` 殘留為 dead code 可刪、目前階段「不要一次全搬 40+ 指令」是正確策略。
- 結論：本次改動 **無 P0**，已通過 Codex 審查；P1 列為已知 technical debt，後續遷移時同步處理。

**2026-05-18 更新（Wave 0 Codex Review 完成）**：
- 已為 `ShellState` 新增 `set_plan_mode`、`set_chat_mode`、`update_settings`、`set_persona` 等明確方法。
- 主要狀態切換點（/plan、/execute、/mode、/model、/persona、自然語言 trigger、/clear）已全部改用新方法。
- 本地 `plan_mode` 變數已在 main interactive loop 中移除。
- `status_line()` 與 `/status` handler 已完全讀取 `state.*`。
- **Wave 0 Codex Review 結論**（新一批）：
  - **P1**：`/clear` 會連帶清掉 tasks（因為呼叫 `AgentSession.clear()` 會清 tasks + persist）。建議拆分 `clear_context()` 與 `clear_tasks()`。
  - **P2**：`/execute` 只關 plan mode，但未確保切到 `mode=agent`，導致「可以呼叫工具」的訊息可能誤導仍在 chat 模式的用戶。
  - **Good**：API 層級設計正確；把重建 client / 清 context 等副作用留在 handler 是對的；不要急著搬更多指令。
  - **Before Wave 1 建議**：
    1. 把互動路徑剩餘的 `mode`/`settings`/`namespace`/`agent_session` 讀取都改成 `state.*`
    2. 修 dispatch 順序（slash command 應先 drain queued prompt）
    3. 拆分 AgentSession.clear()
    4. 補關鍵轉換的 regression test

**2026-05-18 執行完成**：
- A、B、C 三項硬化已逐一完成並 commit。
- 互動 shell 主要路徑的 state 讀取已大幅統一。
- Wave 0 硬化階段結束。

**Wave 1 進行中（已完成 15 個）**：
- /doctor
- /init
- /tools
- /context
- /history
- /jobs
- /cancel
- /clear
- /handoff
- /resume
- /files
- /read
- /search
- /fetch
- /attach
- /git
- /diff
- /apply
- /review   ← Wave 1.4
- /commit   ← Wave 1.5
- /approval ← Wave 1.6（Git 閉環群最後一個：YELLOW 工具審核政策切換）

Git 閉環群（review → commit → approval）已完整遷移。

**Wave 1.7（模式切換群）**：
- /plan + /execute 已遷移
- /mode、/models、/model、/persona 已遷移

模式切換群全部完成（已 push）。

已完成 27 個。**Wave 1.8（剩餘指令收尾）**：
- /remember、/run、/config 已遷移（已 push）
- /docker 系列已遷移（已 push）
- **/task 已遷移** ← A 最後一戰完成！

**A 階段正式完成**（dispatch 主要指令已全部現代化，已 push）。

---

## 進入 B 階段：Phase A 雙任務統一（MT22）

**Step 2 已完成**：
- `print_config` 已改寫為主要依賴新多任務清單。

**Step 3 已完成**：
- `build_handoff` / `write_handoff` 已改寫為接受 `tasks: list[dict]`，優先顯示新多任務清單。
- 三處 handoff 寫入點（含 auto-handoff）已更新傳入 `current_tasks`。

**Step 4 已完成**：
- Shell 啟動流程已調整說明：明確將 `current_tasks` 視為主要來源，`task = load_task(...)` 僅作為 legacy 相容物件保留。
- Transcript 同時記錄 legacy 與新格式，方便過渡追蹤。

**Step 5 已完成**（本次）：
- 移除頂層 `task = load_task(settings.workspace)` 變數。
- 改為局部 `legacy_task` 僅用於過渡期 transcript 記錄。
- 進一步降低 shell 啟動流程對舊單一任務系統的依賴。

**Step 6 已完成**（本次 - F）：
- 清理 `build_runtime` 相關的 legacy 敘述與心智模型。

**Step 7 已完成**（本次 - G）：
- 移除已無呼叫者的 `print_task` 函式。
- 同步移除 `TaskState` 的 import（cli.py 中對舊單一任務系統的靜態型別依賴進一步降低）。

**Step 8 已完成**（本次 - H）：
- 改善 `print_config` 和 `build_handoff` 的 legacy fallback 邏輯。

**Step 9 已完成**（本次 - I）：
- 建立完整剩餘依賴清單。

**Step 10 已完成**（本次 - K）：
- 抽出 `_get_legacy_task_if_exists()` helper。

**Step 11 已完成**（本次 - L）：
- 在 `build_runtime` 函式加上明確的 MT22 說明，宣告它已完全與舊單一任務系統解耦。
- 確認程式碼中已無任何「為了相容 build_runtime 而保留 TaskState」的過時說法。
- 相關 legacy 敘述已在手冊中同步清除。

**Step 12 已完成**（本次）：
- 將 `_get_legacy_task_if_exists` helper 從 `cli.py` 搬到 `tasks.py`。
- `cli.py` 已移除 `from agentx.task import ...`。
- 這是讓生產程式碼完全脫離舊單一任務模組的重要一步。

**Step 13 已完成**（本次）：
- 根據策略 B 調整 `migrate_single_task_if_needed`：
  - 遷移成功後將舊 `task.json` 改名為帶時間戳的 `task.json.bak.*` 進行備份。
  - 強化備份邏輯（備份失敗時盡力刪除舊檔，避免後續誤用）。
  - 補充多個測試案例驗證備份行為與時間戳機制。
- 整體遷移機制更 robust。

目前遷移機制已改為更乾淨且安全的處理方式。

**Step 14 已完成**（本次 - A 方向持續強化）：
- 大幅強化 `_get_legacy_task_if_exists` 的防禦性與資料品質：
  - 增加檔案大小上限檢查。
  - 增加 status 白名單驗證。
  - 加強異常捕獲。
  - **新增資料正規化**：title 自動 strip + 長度限制、status 自動標準化。
- 補充對應的正規化測試。

**Step 15 已完成**（本次 - A1-1a 逐一強化）：
- 進一步強化 title 清理：移除控制字元。

**Step 16 已完成**（本次 - A1-1b 逐一強化）：
- 加強日期欄位處理：使用寬鬆但可靠的 regex 驗證常見 ISO 格式。
- 對各種常見舊日期格式（含 Z、無時區、帶毫秒）做正規化處理。
- 補充日期格式的邊界測試。
- 這是「逐一強化」日期欄位處理的持續小步。

`build_runtime` 相關的 legacy 相依已清理完畢。

**M. 最終移除舊 `task.py` 前置條件清單（逐條檢核中）**

#### 1. 程式碼依賴層面（必須歸零或完全受控）

- [進行中] `cli.py` 中所有直接使用 `TaskState` 型別的地方已清除
  - 目前狀態：`print_task` 已移除。
  - 剩餘唯一使用：`def _get_legacy_task_if_exists(...) -> TaskState | None`（受控的過渡期 helper）。
  - 評估：已收斂至唯一受控點，符合「完全受控」要求。

下一步繼續檢核下一條。

**目標**：解決雙任務系統分裂問題，讓 `tasks.py` 多任務清單成為唯一真相來源（Single Source of Truth）。

**當前狀態**：
- 舊系統：`task.py` + `TaskState`（單一任務）
- 新系統：`tasks.py` + `.agentx/tasks.json`（多任務清單，AgentSession 已使用）

**計劃**（將逐步執行）：
1. 分析兩個系統目前的使用點與差異
2. 設計 migration 策略（舊 task.json → 新 tasks 清單）
3. 重構 `/task` handler（已 dispatch 化，後續調整邏輯）
4. 更新 handoff、status、AgentSession 等相依
5. 移除/標記舊 `task.py` 為 deprecated
6. 測試 + Codex review

準備開始第一步：現況盤點。

---

## 八、建議的下一個動作（2026-05-18 更新）

**當前進度**：Wave 1 進行中（已 18 個）。Wave 0 狀態統一已基本完成（ShellState 作為主要讀寫來源）。

**下一波推薦**（符合「對標合格 Agent CLI」目標）：
- **Git 閉環群**（最高 ROI）：/review、/commit、/approval、/test — 讓 agent 能真正完成「看 diff → review → 安全 apply → 測試 → 中文 commit + push」完整工程流程。
- 之後再做模式切換群（/plan、/execute、/mode*、/model、/persona）。
- /task 因為子命令複雜，預留最後處理。
- 每波 3~6 個就 commit + 更新本文件 + 執行一次輕量 Codex review。

**大目標對齊**：完成 Dispatch 全遷移後，立即進入 Optimization Roadmap Phase A（雙任務系統統一 MT22），這是 Codex 點名的最大架構債，也是讓 agentX 真正能可靠跑長時段 headless 任務的關鍵。

---

## 九、聯絡與備註

- 這份文件同時會寫進：
  - `docs/CLI_DISPATCH_REFACTOR_HANDOFF.md`（Git）
  - Memory Hall（namespace: `project:agentX`）
  - 本地 session 目錄備份

有任何疑問或想調整方向，歡迎直接在下一個對話中引用本文件。

**Step 19 已完成**（本次 - A1-1d 逐一強化）：
- 增加 title 品質守衛：清理後長度 < 2 則視為無效。
- 這是「逐一強化」資料品質守衛的持續小步。

**Step 20 已完成**（本次 - A1-1d 逐一強化）：
- 進一步激進清理 title：移除前後常見無意義標點（---、【】、「」等）。
- 補充針對標點的測試。
- 這是「逐一強化」title 清理的持續小步。

**Step 19 已完成**（本次 - A1-1e 逐一強化）：
- 擴充 status 映射表，支援更多常見中文舊值（進行中、已完成、待辦、未開始等）。
- 補充中文 status 映射測試。
- 這是「逐一強化」status 處理的持續小步。
