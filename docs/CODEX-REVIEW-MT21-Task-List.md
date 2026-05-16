# Codex Review Briefing — Micro-task 21: Headless Task List 完整體驗

**日期**：2026-05
**負責人**：Claude（依 Maki 指示）
**對應項目**：Headless 優化清單 1.5 Task List 完整體驗

---

## 1. 目標

讓 agentX Headless 模式（`agentx -p --agent`）在執行**中大型、長時間工程任務**時，能夠可靠地使用多任務清單（Task List）作為狀態維持工具，降低本地模型（gemma4:31b 等）在長任務中「健忘」與「失控」的問題。

最終希望 Task List 成為 headless 模式下與 Reflection Guard 同等重要的 scaffolding。

---

## 2. 背景與動機

- Phase A 之前，`AgentSession.tasks` 完全是記憶體物件，重啟或長時間運作後任務狀態會消失。
- 模型雖然被 prompt 強烈要求使用 `task_add / task_update / task_list`，但實際使用率不高（尤其是較弱的本地模型）。
- 我們希望讓 Task List 在 headless 環境中「低門檻、自動化、高可靠」。

---

## 3. 實作範圍（已完成）

### Phase A：基礎持久化（必須先做到）
- 新增 `src/agentx/tasks.py`（完整持久化層）
  - `load_tasks` / `save_tasks`
  - `get_next_task_id` / `find_task`
  - `format_task_list_summary`（後續 B1 共用）
- `AgentSession` 自動在 `__init__` 載入、每次 `add/update/clear` 後自動儲存
- 新增 `tests/test_tasks.py`（6 個單元測試全通過）
- 真實 headless 驗證腳本 `scripts/verify_task_list_persistence.py`

### Phase B：降低模型使用門檻（讓本地模型真正會用）
- **B1**：啟動時自動將任務摘要注入 headless system prompt（`build_headless_agent_system_prompt` 新增 `current_task_summary` 參數）
- **B2**：`task_list` 工具回傳改為使用 `format_task_list_summary`（結構化、易讀），取代原始 dict list
- **B3**：編輯後自動 Reflection 以及 Reflection 後建議 commit 的系統訊息中，也自動附上當前任務摘要

---

## 4. 關鍵檔案與變更摘要

| 檔案 | 類型 | 主要變更 |
|------|------|----------|
| `src/agentx/tasks.py` | **新增** | 完整多任務持久化 + 摘要格式化函數 |
| `src/agentx/loop.py` | 修改 | AgentSession 載入/儲存邏輯、_handle_task_tool、自動 Reflection 注入 |
| `src/agentx/runtime_prompt.py` | 修改 | `build_headless_agent_system_prompt` 新增參數並注入摘要 |
| `src/agentx/cli.py` | 修改 | headless 啟動時自動產生任務摘要 |
| `tests/test_tasks.py` | **新增** | 6 個單元測試 |
| `docs/HEADLESS_OPTIMIZATION_LIST.md` | 修改 | 更新 1.5 進度 |

---

## 5. 設計決策與取捨

- **使用單一 `tasks.json`** 而非與現有 `task.json`（單一任務）合併，保持關注點分離。
- **摘要只在啟動時 + 重要 Reflection 時注入**，而非每次 tool 呼叫後都重算（token 考量 + 複雜度控制）。
- `format_task_list_summary` 同時服務 prompt 注入與 `task_list` 工具輸出，減少重複邏輯。
- 目前摘要是「靜態注入」（啟動時產生），尚未做到任務異動後即時更新 prompt 中的摘要（這是已知取捨）。

---

## 6. 風險與特別在意點（請 Codex 重點審查）

1. **與現有單一任務系統的關係**
   - 目前存在兩個任務系統（`task.py` 單一任務 + `tasks.py` 多任務清單）。是否會造成使用者混淆？未來是否應該整合？

2. **Prompt Token 與模型負擔**
   - 當任務很多時，注入的摘要是否會過長？目前有 `max_active=8` 限制，是否足夠？

3. **動態性不足**
   - 任務在中途被更新後，prompt 裡的摘要不會即時更新（只有下次 Reflection 時才會帶最新狀態）。這是否是可接受的 trade-off？

4. **工具輸出格式**
   - `task_list` 現在回傳的是人類可讀的摘要，而非結構化資料。模型如果需要精確解析某個任務的 id 與狀態，是否會有困難？

5. **測試覆蓋**
   - 目前只有單元測試 + 一個驗證腳本。是否需要更多 AgentSession 等級的整合測試？

---

## 7. 希望 Codex 給的具體回饋

請針對以下問題給出意見（越具體越好）：

1. **整體架構**：這個 Task List 設計是否合理？有沒有明顯的結構問題或未來會踩的坑？
2. **Prompt 注入策略**：目前「啟動時 + Reflection 時」注入的策略是否足夠？還是建議做到更即時的動態注入？
3. **工具設計**：`task_list` 回傳摘要而非原始資料的決定是否正確？有沒有更好的平衡方式？
4. **與單一任務系統的關係**：是否建議短期內就把兩個系統整合？還是維持現狀比較好？
5. **風險優先序**：上面 5 個風險點，你認為哪 1-2 個最需要優先處理？
6. **下一步建議**：如果要繼續強化 Task List，你會建議下一個 micro-task 做什麼？

---

## 8. 補充資訊

- 所有變更都通過了 `tests/test_tasks.py`（6/6 passed）
- 已執行過真實 headless 驗證腳本，確認持久化在模擬中斷後可正確還原
- 目前只影響 headless 模式（`-p --agent`），對純互動模式影響極小

---

**結語**：
這是 agentX Headless 模式在「長期任務狀態維持」上的一個重要里程碑。希望 Codex 能從架構、實用性、以及對本地模型友善程度三個面向給出誠實且具體的評價。

謝謝。