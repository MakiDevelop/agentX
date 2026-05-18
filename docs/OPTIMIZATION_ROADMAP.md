# agentX Optimization Implementation Roadmap

**決策日期**：2026-05  
**決策者**：Claude（獲 Maki 完全授權決定實作順序）  
**目標**：讓 agentX 從「優秀的本地工程 agent shell」進化成「弱模型也能可靠承接中大型 headless 任務」的生產級工具。  
**原則**：風險先、基礎先、Leverage 最近 MT20/MT21 成果、每一步都可 Codex review、可獨立 commit。

---

## 總體順序（已鎖定）

| Phase | 主題 | 優先理由 | 預估 micro-task |
|-------|------|----------|-----------------|
| **A** | 雙任務系統統一（最大架構債） | Codex review 直接點名最高風險；繼續分裂會讓後續所有改動都踩雷 | MT22 |
| **B** | Headless 核心可靠性（記憶 + 錯誤恢復） | 直接打中「長任務不失憶、不卡住」的核心價值 | MT23, MT24 |
| **C** | 維護性與一致性（Prompt + Plan 流程） | 避免 prompt 漂移；讓 plan mode 真正可用 | MT25 |
| **D** | 體驗平權 + 可觀測性 | 讓互動模式也吃到新成果；長 headless 跑完後人類能看懂 | MT26 |
| **E** | 測試、效能、清理 | 讓專案長期可維護 | 持續 |

**為什麼這個順序？**
- 最高風險（雙任務）必須最先解決，否則後面任何 scaffolding 都會有兩套狀態。
- Context（記憶）與 Error Recovery 是 headless 長任務的兩大命脈，優先於 UX。
- Prompt 統一放在雙任務穩定之後，避免同時改動多個核心注入點。
- 最後才做「好看但不關鍵」的測試與清理。

---

## Phase A: 架構衛生 — 雙任務系統統一（MT22）

**問題**：
- `task.py` + `TaskState`（單一任務，給 `/task`、handoff、互動狀態用）
- `tasks.py` + 多任務清單（`.agentx/tasks.json`，給 headless AgentSession 長期狀態用）
- 兩套持久化、兩套 API、兩套 prompt 注入、互動與 headless 體驗分裂。

**決策方向（已鎖）**：
- **以 `tasks.py` 多任務清單為唯一真相來源**（source of truth）。
- 單一 `TaskState` 逐步退場：先做相容層（把舊 `task.json` 自動 migrate 成多任務清單中的「主要任務」），再移除。
- `/task` 命令、handoff、`/status` 全部改成以多任務清單為基礎（可顯示「目前主要任務」+ 完整清單）。
- 保留 `task_add / task_update / task_list` 工具不變（已是正確設計）。

**成功標準**：
- 刪除 `src/agentx/task.py` 與 `tests/test_task.py`（或標記 deprecated）。
- 所有現有 `/task` 行為在互動模式下仍正常（向後相容）。
- headless 的 Task List 功能不受影響。
- 單元測試 + 手動驗證 headless + 互動兩種模式都通過。
- Codex review 通過後 commit。

**風險與緩解**：
- 互動使用者習慣改變 → 用 migration + 清楚的 `/task` 輸出格式說明。
- handoff 相容 → 舊 handoff 仍可讀，新 handoff 寫多任務摘要。

**下一步行動**（本 roadmap 啟動後立即執行）：
1. 寫 Decision Record（簡短）放進本次改動 commit。
2. 實作 migration 邏輯（啟動時偵測舊 `task.json` 轉成多任務）。
3. 重構 cli.py 中的 task 相關 handler。
4. 重構 handoff 產生邏輯。
5. 更新 loop.py（如有需要）。
6. 刪除舊檔案 + 更新測試。
7. 執行完整測試 + 真實 headless + 互動驗證。

---

## Phase B: Headless 核心可靠性

### B1. Context Compaction v2（MT23）

**現況**：`AgentSession.compact()` 是極簡的「最後 N 則 + 粗暴截斷摘要」。長任務很容易失憶。

**目標**：
- 建立 `ContextCompactor` 抽象（可插 LLM summarizer）。
- 先實作強化的 extractive + 結構化摘要（保留任務清單、最近決策、未完成編輯）。
- 為未來「呼叫本地模型做 semantic summary」鋪路。

**成功標準**：
- `/compact` 後的摘要明顯更有用（人工 review）。
- 壓縮後仍能正確延續長任務（用 verify 腳本或新整合測試驗證）。
- 沒有 regression 到現有 compact 行為。

### B2. 錯誤恢復策略成熟化（MT24）

**現況**：ErrorClassifier + STUCK 偵測已存在，但恢復建議仍偏被動。

**目標**：
- 建立「恢復 playbook」字典（BACKTRACK、CHANGE_EDIT_STRATEGY、ESCALATE、SIMPLIFY_SCOPE 等）。
- 在 STUCK 時自動產生更具體、可執行的建議 + 自動建議 model 採取哪個 playbook。
- 增加有限的「自動安全重試」策略（只針對 TRANSIENT）。

**成功標準**：
- HEADLESS_OPTIMIZATION_LIST.md Phase 1.1 「更好的錯誤恢復策略」標為完成。
- 真實卡住情境下，模型能更快脫困（手動模擬測試）。

---

## Phase C: 維護性與一致性

### C1. 系統 Prompt 統一（MT25）

**問題**：三份極相似的 prompt 分散在 `runtime_prompt.py`，差異只在「headless 要更果斷」等少數段落。

**目標**：
- 抽 `BASE_AGENT_PRINCIPLES` + `HEADLESS_DELTA` + `INTERACTIVE_DELTA`。
- 單一函數根據模式產生最終 prompt。
- 所有原則（安全、workflow、reflection guard、task 使用）只寫一次。

**成功標準**：
- 任何原則修改只需改一處。
- 現有 headless / 互動行為完全一致（除了刻意差異）。

### C2. Plan Mode → Execute 順暢流程（MT25 延伸）

- 支援 `--plan-then-execute` 或從 plan transcript 繼續執行。
- Plan 完成後的 final answer 能被後續執行階段自動解析為初始任務清單。

---

## Phase D: 體驗平權 + 可觀測性

### D1. 互動模式吃到多任務清單（MT26）

- `/task` 完全改用多任務清單呈現（支援 `task list`、`task add`、`task update`、`task focus <id>`）。
- `/status` 顯示目前主要任務 + 進行中任務數。
- 讓互動使用者也能享受 MT21 的成果。

### D2. Headless 可觀測性（MT26）

- 每次 tool call / reflect / final 都可選記錄到結構化 log（` .agentx/logs/` 或 transcript 增強）。
- 暴露「本輪 token 估計、reflection 次數、錯誤次數、任務進度」給 `/status` 與 transcript。
- 長 headless 結束後能快速產生「執行摘要」。

---

## Phase E: 測試、效能、清理（持續）

- TUI + PromptJobQueue 端到端整合測試。
- `run_tests` 工具支援「只驗證受影響模組」（或可配置策略）。
- 刪除 stale `coordinator.pyc` 相關殘留（如果還有）。
- 提升 `test_cli_dispatch.py` / `test_plan_mode.py` 覆蓋率到真正 AgentSession 等級。
- 效能：大型 repo 的 list_files / search_text 快取或限制。

---

## 追蹤與治理

- 每個 Phase 結束前更新本檔 + HEADLESS_OPTIMIZATION_LIST.md 的 Progress Update。
- 所有非 trivial 變更（尤其是 A、B 兩 Phase）必須準備 Codex briefing，通過 review 後才算完成。
- 每完成一個 micro-task 立即 commit（中文訊息 + 逐檔 stage）。
- 重大架構決策（如 Phase A 統一方向）寫 Decision Record 放進 commit。

---

## 目前狀態（2026-05 後更新）

- **Phase A 已完成**（MT22 全系列）：
  - 雙任務統一 + Codex 修復 + handoff 豐富化
- **Phase B1 已完成**（MT23）：
  - Context Compaction v2 基礎 + 穩定性打磨（自動觸發、DI、bootstrap 保護）
- **Phase B2 已開路**（MT24）：
  - 新增獨立 `RecoveryPlaybook` 模組
  - 擴充 RecoveryAction（新增 SIMPLIFY_SCOPE、VERIFY_ASSUMPTION、ABANDON_AND_RESTART 等）
  - STUCK 介入訊息大幅結構化，建議更有優先序與信心值
  - 恢復策略從「散落經驗法則」變成可維護的 playbook
  - 測試從 91 → 94 passed
- 測試 91 passed，ruff 乾淨。
- Codex review 意見已全部處理並記錄在 `CODEX-REVIEW-MT22-Dual-Task-Unification.md`。
- 其餘 Phase 依序解鎖。
- 任何新發現的優化項目，優先塞進對應 Phase，而非破壞順序。

**本 roadmap 由 Claude 負責維護與執行，直到 Maki 另有指示。**

---

**參考文件**：
- `docs/HEADLESS_OPTIMIZATION_LIST.md`
- `docs/CODEX-REVIEW-MT21-Task-List.md`
- `src/agentx/loop.py`, `cli.py`, `task.py`, `tasks.py`, `runtime_prompt.py`

---

*最後更新：見 git log*