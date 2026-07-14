# agentX Headless 模式 未來優化清單

**建立日期**：2026-05-16
**來源**：本次長時段 session 對 Headless 模式（`agentx -p --agent`）的系統性討論與實作

本清單以「讓 Headless 模式能穩定承接中大型工程任務，作為 Claude CLI / Codex CLI / Gemini CLI 的暫時代理」為核心目標，分為三個等級。

## Phase 1：核心可用（必須先做到，能真正拿來做事）

### 1.1 基本執行穩定性
- [x] 避免長時間無效 reflection 迴圈（reflection 迴圈保護機制） — Micro-task 20 已實作（AgentSession consecutive_reflections + guard 警告 + 重置邏輯 + 單元測試 + prompt 提及）
- 更好的錯誤恢復策略
- [x] 清晰的 exit code 設計（0 success / 1 task-tool-test failure / 2 agent control failure / 130 cancelled；`-p` 與 `ask` 共用；2026-07 起優先使用 `AgentSession.last_termination` / `last_failing_tools`，文字分類僅作 fallback）

### 1.2 Plan Mode 完整支援（--plan）
- Headless 下的規劃品質提升（更結構化、更 actionable）
- 規劃完成後的自然轉執行機制（plan-then-execute）
- 更好的「規劃品質評估」引導

### 1.3 精準編輯與驗證閉環
- 編輯後的自動測試 + Reflection 機制在 headless 下的穩定度
- Reflection 品質優化（更結構化）
- 模型在 Reflection 後更清楚下一步

### 1.4 基本工程流程支援
- 自然走完「規劃 → 實作 → 驗證 → 建議 review → 建議 commit」
- 模型主動建議 commit 的時機與品質

### 1.5 Task List 管理
- Task List 在 headless 長任務中的完整體驗
- 模型更習慣主動使用 Task List

## Phase 2：應該具備（好用程度）

- Headless 專屬行為模式（已部分完成）
- Plan → Execute 順暢轉換（--plan-then-execute 等）
- 更好的決策與主動性
- 錯誤恢復與穩定性強化

## Phase 3：進階優化

- 結構化輸出支援（JSON mode）
- 日誌與可觀測性
- 從 transcript / handoff 繼續執行
- 更細的行為控制參數
- Context 管理優化
- 效能與 token 使用優化

**記錄位置**：
- Git：`docs/HEADLESS_OPTIMIZATION_LIST.md`（戰術清單）
- Git：`docs/OPTIMIZATION_ROADMAP.md`（2026-05 起正式實作順序與決策，由 Claude 全權決定順序後建立）
- memhall：已寫入（namespace: project:agentx）
- session dir：`~/Documents/agent-council/2026-05-16-agentx-headless-plan-mode/OPTIMIZATION_LIST.md`

**建立者**：Claude（依據本次長時段 session 與 Maki 的討論）

**Progress Update (Micro-task 21, 2026-05)**：
- [x] 1.5 Task List 完整體驗（Phase A + B 完成）
  - Phase A: 持久化基礎（`tasks.py` + `AgentSession` 自動載入/儲存 + 真實驗證）
  - Phase B: 降低使用門檻（初始 prompt 自動注入 + `task_list` 工具優化 + 自動 Reflection 注入）
- Codex review 後已處理主要問題：
  - 修復 `format_task_list_summary` 的 `max_active` 切片 bug
  - 強化 `task_update`（字串 task_id 容錯 + status 白名單）
  - 加強 `load_tasks` schema 保護
  - 修復驗證腳本（改用 TemporaryDirectory）
  - 調整 Reflection 流程中的誤導性指令為誠實版本

**Progress Update (錯誤恢復策略, 2026-05)**：
- 階段一：錯誤分類 + 基礎恢復框架（已完成）
  - 建立 `ErrorType` 與 `ErrorContext`（`src/agentx/errors.py`）
  - 實作規則為主的 `ErrorClassifier`（`src/agentx/error_classifier.py`）
  - 在 `AgentSession` 整合有限次自動重試（TRANSIENT / CALL_ERROR）與錯誤發生時的結構化 Reflection 引導
- 階段二步驟1：STUCK 偵測 + 恢復策略建議（已完成）
  - 實作 `_detect_stuck`：同工具連續同類錯誤達到門檻即判定為 STUCK
  - 實作 `_generate_recovery_suggestions`：根據錯誤歷史自動產生具體建議（BACKTRACK、CHANGE_STRATEGY、ESCALATE_TO_USER 等）
  - STUCK 時自動插入強烈介入訊息 + 恢復建議，並強制模型進行深度 Reflection
- 相關測試：新增 `tests/test_error_classifier.py`（8 個測試全通過）
- 已 commit 並 push（commit 2fd440c）

**2026-05 正式實作 Roadmap 啟動**：
- 建立 `docs/OPTIMIZATION_ROADMAP.md`，由 Claude 全權決定 5 Phase 實作順序（風險優先、基礎優先）。
- Phase A（雙任務系統統一，MT22）**已完成**：task.py 移除、cli 污染清除、test 最終清理、診斷保留。詳見 MT22-Legacy-Removal-Checklist.md 。
- 後續 Phase 將依序解鎖 Context Compaction、錯誤恢復成熟化、Prompt 統一等。
