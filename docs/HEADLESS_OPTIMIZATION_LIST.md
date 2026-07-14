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

**Progress Update (Headless Plan-then-Execute, 2026-07)**：
- [x] `agentx -p ... --agent --plan-then-execute` 會在同一個 `AgentSession` 內先跑 plan-only，再切換為 execution mode。
- [x] `agentx ask ... --plan-then-execute` 走同一套 two-phase headless runner。
- [x] 輸出會分成 `## Plan` 與 `## Execution`，方便人或上游 agent 判讀。
- [x] JSON mode 會額外提供 `phases=[{name:"plan"},{name:"execution"}]`，讓 script 不必自行切割 `output`。
- [x] 修正舊行為：不再把 `plan_then_execute` 當成整輪 `plan_only`，避免永遠不能執行工具。

**Progress Update (Headless JSON Observability, 2026-07)**：
- [x] `--workspace PATH` / `--cwd PATH` 可在單次 headless run 指定目標 repo；prompt-file、`.agentx/config.toml`、session save/resume 都以該 workspace 為準。
- [x] `--approval ask|auto|off|strict|auto-approve|deny` 可在單次 headless run 覆蓋 YELLOW 工具 approval policy，不用改 `.agentx/config.toml`。
- [x] `agentx --prompt-file briefing.md --agent ...` 可從 workspace 檔案讀取長 prompt，適合多代理 briefing / script automation；與 `-p` 互斥並阻擋 workspace escape。
- [x] `cat briefing.md | agentx --stdin --agent ...` 可從 stdin 讀取 prompt；與 `-p` / `--prompt-file` 互斥。
- [x] `--backend BACKEND` 可在單次 headless run 覆蓋 LLM backend（例如 `llama_cpp`），不用改 `AGENTX_BACKEND`。
- [x] `agentx --list-backends` / `agentx backends` 可離線列出已註冊 LLM backend，支援 JSON 輸出。
- [x] `agentx --list-models` / `agentx models` 可列出所選 backend 目前可用模型，支援 `--backend` / `--base-url` / JSON。
- [x] `agentx --version` / `agentx version` 可輸出 agentX 與 Python runtime 版本，支援 JSON 輸出。
- [x] `--base-url URL` 可在單次 headless run 覆蓋 LLM backend base URL，不用改 `AGENTX_OLLAMA_URL`。
- [x] `--model MODEL` 可在單次 headless run 覆蓋模型，不必改環境變數或進 shell 後 `/model`。
- [x] `--timeout SECONDS` 可在單次 headless run 覆蓋 LLM request timeout，適合慢本地模型或長 context。
- [x] `--run-timeout SECONDS` 可限制整輪 headless run deadline；逾時回 `termination=timeout`、exit code 124，並透過 cancel_event 嘗試中止模型串流。
- [x] `agentx -p ... --json` 與 `agentx ask ... --json` 可輸出機器可讀 payload。
- [x] `--output-format json` 可作為 `--json` 的 script-friendly 等價入口；非法格式會直接失敗。
- [x] `--output-format jsonl` 可輸出單行 event envelope（`result` / `dry_run` / `version` / `backends` / `models`），方便 pipeline 用同一套 event parser 消費。
- [x] `--quiet` 可壓掉 plain stdout、保留 exit code；搭配 `--json` 時仍輸出 JSON payload。
- [x] `--result-output PATH` 可把 headless result payload 寫入 workspace 內 artifact；plain stdout 時寫 JSON，`--output-format jsonl` 時寫 JSONL event，拒絕 workspace escape 與覆蓋既有檔案；`--result-output-format auto|json|jsonl` 可讓 artifact 格式獨立於 stdout。
- [x] `agentx handoff-inspect --require-handoff` 可把 result artifact 當成接手 gate：需要 `needs_handoff=true` 與 `resume_command`，否則 exit 1；可搭配 `--field`、`--output-format jsonl` 與 `--use-payload-exit-code`。
- [x] `agentx handoff-inspect --require-schema-version` 可拒絕舊版或未知 headless result payload contract；inspection output 也會顯示 `schema_version`。
- [x] `agentx handoff-inspect --next-prompt-file PATH` 可把 `resume_command` 的 `-p '<next prompt>'` 改成 `--prompt-file PATH`，方便 Codex/Grok runner 用長 briefing 接手。
- [x] `agentx handoff-inspect --resume-output-format json|jsonl` 可改寫接手命令的輸出格式；JSONL runner 可直接產生 `--output-format jsonl` 續跑命令。
- [x] `--dry-run` 可驗證 headless prompt/workspace/config/override 解析結果，不呼叫模型、不跑工具、不寫 session；支援 JSON 輸出。
- [x] `--no-memory` 可在單次 headless run 關閉 Memory Hall / AMH 讀寫；工具介面保留但使用 no-op NullMemoryClient，適合 CI、多代理隔離與不可污染記憶的任務。
- Payload 包含 `schema_version`、`output`、`exit_code`、`termination`、`failing_tools`、`stats`。
- `stats` 目前提供 message count、粗估 context tokens、model turn count、tool call count、reflection count、error count、compaction count、pending verifies、task counts。
- `log_summary` 目前提供 termination、tool outcomes、successful/failing tools、recent errors、recovery suggestions、pending verifies、handoff summary，讓 script/其他 agent 不必解析自然語言輸出即可判斷執行狀態與下一個恢復動作。
- `handoff_summary` 會用 deterministic runtime state 輸出 status、needs_handoff、failing_tools、pending_verifies、last_error、task_counts、recovery_actions、primary_recovery、recovery_checklist、next_steps；若有 session_path 也會附 `resume_session` 與 `resume_command`，不額外呼叫模型。
- 穩定 payload 契約記錄於 `docs/HEADLESS_PAYLOAD_CONTRACT.md`；外部 runner 應以此文件與測試為準。
- 一般文字輸出保持相容；JSON 模式會抑制 trace，避免污染 stdout。

**Progress Update (Headless Session Resume, 2026-07)**：
- [x] `agentx -p ... --agent --save-session` 可保存 `.session.jsonl`。
- [x] `agentx -p ... --agent --resume-session latest|NAME` 可從目前 workspace 的 `.agentx/sessions/*.session.jsonl` 恢復後繼續執行。
- [x] JSON payload 回報 `session_path`，方便 script 串接下一輪。
- [x] `--session-output PATH` 可把 headless session JSONL artifact 寫到指定 workspace 內路徑；拒絕 workspace escape、拒絕覆蓋既有檔案、不可與 `--resume-session` 混用。
- [x] `agentx ask` 走同一套 headless runner，支援 `--save-session` / `--resume-session` / `--json` / `--max-steps`；`agentx -p --agent` 也支援 `--max-steps`。
- [x] Resume 會還原 runtime state：tool outcomes、file ops、pending verifies、last termination、failing tools 與 observability counters，避免跨 run stats 歸零。

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
  - Headless JSON `log_summary.recovery_suggestions` 會輸出結構化 action/confidence/description/rationale，方便 script 或其他 agent 接手恢復。
- 相關測試：新增 `tests/test_error_classifier.py`（8 個測試全通過）
- 已 commit 並 push（commit 2fd440c）

**2026-05 正式實作 Roadmap 啟動**：
- 建立 `docs/OPTIMIZATION_ROADMAP.md`，由 Claude 全權決定 5 Phase 實作順序（風險優先、基礎優先）。
- Phase A（雙任務系統統一，MT22）**已完成**：task.py 移除、cli 污染清除、test 最終清理、診斷保留。詳見 MT22-Legacy-Removal-Checklist.md 。
- 後續 Phase 將依序解鎖 Context Compaction、錯誤恢復成熟化、Prompt 統一等。
