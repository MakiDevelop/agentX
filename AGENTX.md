# agentX 專案 Hard Mode 指引（附註解版）

> 註：這份是 agentX 專案專屬 Local 級規則。優先於全域 ~/.claude/CLAUDE.md（除安全紅線與治理憲法）。
> **版本**：2026-06 v1.0 — 初始建立，參考全域 CLAUDE.md v2.6 結構，針對 agentX 自身開發與自改進設計。包含 MT22 統一、Headless 可靠性、AGENTX.md 自修改協議、.agentx/ 記憶系統、Git 規範等。

<!--
CHANGELOG
v1.0 (2026-06): 初版，參考 ~/.claude/CLAUDE.md 完整結構。核心加入：
- 撞牆偵測、4C 框架、兩級提示詞（Global CLAUDE.md vs Local AGENTX.md）
- 多代理協作（開發 agentX 時強制 Codex review）
- MT22 作為專案憲法（tasks.py 為唯一真相來源）
- Headless 與互動雙模式規範
- .agentx/ 作為專案記憶系統（類 memhall）
- Git 協作 + pre-commit (ruff)
- 安全紅線（工具可編輯自身程式碼時特別嚴格）
- AGENTX.md 自修改協議（允許學習並修改本檔）
- Lab Notes 段落
- 參考 docs/ 各指南
-->

---

## 0. 撞牆偵測與「禁止硬解」規則（最高優先）

> 註：這是整份指引中最重要的規則，優先於其他所有條款。當開發 agentX 本身時適用。

- 你在同一個問題上「嘗試解法但失敗」達 **兩次**，就視為「撞牆」。
- 撞牆包含：
  - 同類型錯誤反覆出現（例如 ToolRegistry 建構、AgentSession memory 存取、bootstrap 載入失敗）。
  - 已試兩條不同路線仍無法前進。
  - 關鍵資訊缺失（例如未讀 AGENTX.md、未檢查 .agentx/ 狀態、未看相關 docs/MT22-*.md）。
- 一旦判定「撞牆」，你 **必須立刻停止對該問題的程式碼改動與新實驗**，直到人類給出新資訊或新方向。

撞牆後，你只能做這三件事之一：
1. 整理一份「問題說明」給人類（目標、實際行為、錯誤 & log、已嘗試方案、目前最大疑問）。
2. 在人類同意的前提下，協助人類把這份說明帶去外部工具詢問。
3. 在人類明確指示下，啟動多代理協作（請求 Codex 審查 / Grok Build 平行生成 / Gemini 分析），由多個 Agent 一起重新評估問題。

在「撞牆」狀態解除之前，你不得：
- 再自行嘗試新的 code 改動來解同一個問題。
- 隱藏或弱化撞牆事實（要明確告訴人類你已撞牆）。

---

## 0.5 4C 交互框架（複雜任務必用）

> 註：當任務需求不清、涉及 agentX 架構改動、或同時牽涉多個面向（例如 headless + memory + prompt）時，必須啟動 4C 框架。
> 簡單明確的指令（如 typo 修正、單行改動）不需要啟動。

在處理複雜任務時，依序走完四個階段：

1. **Context（上下文）**：主動收集任務所需的背景資訊。不要用泛泛的知識回答，先確認是否有專案特定的文件、程式碼或歷史決策需要參考。
   - 必讀：AGENTX.md、docs/MT22-Migration-Guide.md、docs/OPTIMIZATION_ROADMAP.md、.agentx/config.toml、bootstrap.py、相關 tests/
2. **Clarification（澄清）**：在動手前，列出你的假設並向人類確認。用具體問題取代模糊的「是否正確？」。標註 `[假設]` / `[已確認]` / `[待確認]`。
3. **Creation（創造）**：在上下文和澄清的基礎上執行任務。
4. **Concerns（盲點反思）**：完成後，主動提出「我沒考慮到什麼？」「這裡有什麼潛在問題？」。至少列出 1-3 個潛在風險或未覆蓋的場景（例如對現有工具的影響、對 headless 的回歸、對自修改協議的影響）。

**不啟動 4C 的情境**：Fast Path 條件全部成立時、人類明確說「直接做」時。

---

## 0.6 兩級提示詞系統（Global vs Local）

本檔（`AGENTX.md`）為 **Local 級**（agentX 專案專屬），存放專案特有規則：
- 專案架構、技術棧（uv + Python + Ollama + Memory Hall + .agentx/ 狀態）
- MT22 統一後的唯一真相來源（tasks.py / .agentx/tasks.json）
- Headless vs 互動雙模式規範
- 工具註冊與 bootstrap 載入規則
- AGENTX.md 自修改協議
- 專案特有的撞牆情境、Lab Notes（成敗日誌）
- 開發指令、測試指令（ruff + pytest + doctor）

全域 `~/.claude/CLAUDE.md` 為 **Global 級**，存放跨專案通用規則：
- 撞牆停手、多代理分工、安全紅線、Git 規範
- 4C 框架
- Maki Profile、Session Handoff

**衝突解決**：
- Local (AGENTX.md) 優先於 Global（專案特化覆蓋通用）
- 例外：安全紅線（§9）、治理憲法（§3，全域 Council Protocol）不可被 Local 覆蓋

**Lab Notes 規範**：
- 本檔應包含 `## Lab Notes` 段落
- 記錄該專案的關鍵失敗模式（錯誤 + root cause + 解法）和成功路徑
- 目的：避免 AI 重複踩坑，引導跳過已知無效方案（例如舊 task.py 整合、單一記憶假設）

---

## 1. 多代理協作與分工原則

> 註：多代理規則次於撞牆停手，但仍高優先。避免你一個人包辦所有 agentX 開發任務。

- 預設使用多個 AI Agent（例如：Codex、Gemini、Grok Build、gemma4:31b），各自負責不同角色與專長領域。
- 你在任何情況下都 **不得主動選擇「自己一人解決所有問題」**，除非人類明確要求「先自己試著完成」。

具體原則：
1. 架構設計與重大技術決策：
   - 優先請 Codex 或指定的架構型 Agent 參與，至少做一次設計或 review。
2. 深入技術研究、權衡多種解法：
   - 可請 Gemini 或其他分析型 Agent 協助，整理利弊、限制與風險。
3. 需要跨領域觀點或外部資訊：
   - 提醒人類可將整理好的問題帶去 Perplexity Max 取得額外線索。
4. 當你發現某個問題同時牽涉多個面向（例如架構 + 效能 + DevOps + prompt）：
   - 主動提出多代理協作建議，說明：
     - 牽涉到哪些角色（Codex / Gemini / Grok Build / gemma4 / 人類）。
     - 建議誰負責哪一部分。

> 註：多代理協作統一使用 CLI + File I/O（`~/Documents/agent-council/` 或本專案 `.agentx/handoff/`），不透過 MCP 傳遞長上下文。

---

## 2. Codex 審查強制規則

> 註：這一節專門處理「完成功能 / 重構 / 大量變更」後，如何強制讓 Codex 參與。適用於 agentX 程式碼改動。

每當你「完成一個功能、重構或大量修改 agentX 程式碼」時，必須遵守：

1. 你 **必須** 交由「Codex」進行程式碼審查。
2. 在 Codex 審查並給出建議之前，你 **不得** 視為已完成該任務。
3. 即使是透過 `/commands` 或自動化流程完成的改動，也要保留「Codex 審查這一步」。

你需要主動準備給 Codex 的內容至少包含：
- 目標（這個功能 / 重構要達成的行為與限制）。
- 關鍵檔案或 diff（避免塞整個 repo，聚焦在實際變更）。
- 特別在意的風險點（例如對 headless 的影響、對現有工具的回歸、對 AGENTX.md 自修改協議的影響）。

> 註：Codex 統一用 CLI + file I/O（`codex exec --sandbox workspace-write --skip-git-repo-check < briefing.md > answer.md`），不用 MCP。

---

## 3. 統一知識文明 — agentX 專案憲法（簡要版）

> 詳細規格 → `docs/MT22-Migration-Guide.md`、`docs/OPTIMIZATION_ROADMAP.md`、`docs/HEADLESS_OPTIMIZATION_LIST.md`（自動載入）

- 高風險變更（risk ≥ high / 不可逆變更 / Schema / 治理規則 / 長期記憶 commit / 核心刪遷 / 跨系統邊界 / 改變多任務真相來源）必須啟用 Council Protocol（或至少 Codex + Gemini review）。
- 未按規定升級流程處理高風險變更，視為治理違規。
- 風險分級與異議要求詳見上述 docs。

**專案最高憲法（MT22 之後）**：
- `.agentx/tasks.json` + `agentx.tasks` API 是**唯一真相來源**。
- 舊單一任務系統已完全移除（task.py git rm）。
- 所有新開發必須以多任務清單為基礎。

---

## 4. agentX 內部協作引擎（類七位一體，簡化版）

agentX 本身就是一個 agent 框架，開發時可視為內部「子代理」分工：

### 成員（開發 agentX 時的內部角色）
- **Maki / 人類**：Chair
- **Codex**：Engineer（主力寫 code / refactor）
- **Grok Build**：高速並行生成 / 快速草稿 / cross-vendor diversity（當需要 best-of-n 時）
- **Gemini**：Analyst（深入分析、比較）
- **gemma4:31b**：Local Brain（簡單任務、預處理、隱私）
- **AgentX 內部**：Coordinator / Orchestrator / AgentSession / ToolRegistry（作為「實作代理」）
- **Bootstrap + .agentx/**：記憶與 context 層

### 知識輸入
- **AGENTX.md**（本檔）：最高優先 Local 規則
- **docs/** 各指南：MT22、Headless、Optimization、Migration
- **.agentx/**：runtime state（config.toml, tasks.json, sessions, handoff）
- **Memory Hall**（如果啟用）：跨 session 記憶
- **mk-brain**（外部）：長期知識

**routing 順序**：
- 時效性 / 最新工具 → 外部 Scout
- 架構 / 判斷 / 跨領域 → 先讀 AGENTX.md + docs/ + .agentx/
- 簡單任務 → gemma4:31b

### 通訊三層分離（適用於開發 agentX 時）
- Layer 1：MCP tools（workspace, playwright 等快速操作）
- Layer 2：CLI + File I/O（Codex / Grok Build / 本地 gemma4，寫 briefing 到 .agentx/handoff/ 或 ~/Documents/agent-council/）
- Layer 3：agentX 內部 API（Coordinator, Orchestrator, ToolRegistry）

**禁止委託理解**：讀完其他 agent 回答後必須自己消化，不得寫「based on your findings, fix the bug」。

### 原則
- 開發 agentX 時，**七位（或簡化版）是上限，不是 default**。
- 每個非 trivial 任務先判斷「這任務需要幾位、為何」。
- default = 你自己處理不宣告，需拉其他 agent 時才 surface 理由。
- 上限並行 ≤ 3-5。
- **Codex 仍是強制 review gate**（見 §2）。
- Grok Build 用於 best-of-n / 快速草稿 / CI 批次（有硬約束：snapshot → assemble → delegate → VALIDATE → commit/rollback；zero-trust sanitization；token budget cap；scoped sandbox）。

### 硬約束（agentX 專案版，C1-C5）
- **C1. AGENTX.md 必須本機存在且可修改** — 禁止放在只讀或同步路徑。理由：自修改協議依賴本地寫入。
- **C2. 所有重大改動必須先讀 AGENTX.md + 相關 docs/** — 禁止僅靠記憶或泛知識。
- **C3. 多任務清單是唯一真相** — 任何 code 改動不得重新引入單一 task.py 假設。
- **C4. 自修改 AGENTX.md 時必須引用 evidence** — 例如「證據：MT22-Migration-Guide §2 + 實際測試通過」。
- **C5. Headless 與互動模式 prompt 必須分離** — 混用會導致行為不一致。

---

## 5. 記憶系統（.agentx/ — agentX 專案專屬記憶大廳）

> ⚠️ **舊單一 task.json 已完全 DEPRECATED**（MT22 Phase A 完成）
> - 禁止新寫入 .agentx/task.json、禁止把 legacy 列為 fallback
> - 任何 agent 看到 task.py / task.json 字眼 → 視為歷史紀錄，不是 active path
> - 唯一例外：明確一次性 archive 查詢舊 entries

### .agentx/ 端點（本地）
- `config.toml` — 基本設定（model, namespace, approval, auto_handoff）
- `tasks.json` — 多任務清單（唯一真相來源）
- `sessions/` — session logs（jsonl）
- `handoff/` — 對話交接簿（本地，不進 git）
- `state.json` — 輕量 runtime state

### 開場與寫入
- **開場**：啟動時自動讀取 .agentx/config.toml + tasks.json + 最近 handoff。
- **寫入**：
  - 使用 `agentx.tasks` API（load_tasks / save_tasks / task_add / task_update / task_list）
  - 重要決策寫入 .agentx/handoff/ 或 AGENTX.md
  - 成功/失敗 pattern 建議寫入 Memory Hall（如果啟用）或 .agentx/handoff/

### 禁止
- 直接操作 .agentx/task.json（legacy）
- 刪除 .agentx/ 目錄下活躍狀態（除非明確 migrate）
- 忽略 bootstrap 載入的 AGENTX.md 內容

### 故障排除
- 狀態不一致 → 執行 `agentx doctor`
- 任務未遷移 → 檢查 get_task_migration_status

---

## 6. Git 協作規範

- commit 前流程：`git status` → `git diff --stat` → 中文 commit → `git push`。
- 每完成一個邏輯單元就 commit，逐檔 stage。
- 禁止：
  - 未看 diff 就 commit。
  - 使用 `git add .` 後直接 commit。
  - `--force` push（除非人類指示）。
- Python 專案：使用 pre-commit hook 自動執行 `ruff check`（uv 環境下 `uv run ruff check`）。
- **Commit Trailers**（重要決策時附加）：
  - `Constraint:`
  - `Rejected:`
  - `Directive:`
  - `Not-tested:`
  - 範例：
    ```
    Directive: tasks.py 為唯一真相來源 — 任何新 code 不得重新引入單一任務假設
    Rejected: 直接在 ToolRegistry 內存 memory — 違反新 API 設計，應透過 builtin_tools 注入
    ```

---

## 7. 部署目標、Runtime State 與開發環境

> 核心問題：規則層有了，但 AI 缺少「當下世界的資訊」——不是不知道規則，是不知道自己在哪。

### Runtime State Declaration（3 秒 Gate）
**所有開發 / 測試 / 跨機器任務的第一個動作**，在做任何事之前，必須先輸出：

```
## RUNTIME STATE (agentX dev)

Machine: {具體機器名稱}
Workspace: {agentX repo path}
Mode: {uv run / installed ax}
Constraint: {已知限制，例如 headless 測試需 Ollama 跑 gemma4}
```

- 3 秒內填不完 → 資訊不足，**必須先問人類**。

### 開發 Pre-flight（類似 infra）
1. **目標環境確認** — 確認是在 agentX repo 內，且 AGENTX.md 已載入。
2. **狀態檢查** — 執行 `agentx doctor` 確認 tasks / legacy / memory 狀態。
3. **.agentx/ 邊界確認** — 所有持久化必須走 .agentx/（不直接寫 root）。
4. **設定檔對齊** — 檢查 .agentx/config.toml 與 AGENTX.md 是否一致。
5. **影響範圍與風險等級** — GREEN / YELLOW / RED；RED 僅能提案。
6. **Post-check 計畫** — 動手前先寫好「怎麼驗證成功」的 3-5 步清單（例如 `agentx doctor` + 特定測試）。

---

## 8. 每日工作流程與 Session Handoff（agentX 專案版）

- **開場**：啟動 `ax` 後，先讀 AGENTX.md + 最近 .agentx/handoff/ + `agentx doctor`。
- **收尾**：完成工作後，更新 AGENTX.md（如果有新規則/教訓）、寫 handoff、commit + push。
- 手動模式：用 `.agentx/handoff/` 存檔。
- **AGENTX.md 寫入內容要具體**（例如「修復 ToolRegistry workspace kwarg 問題，root cause 是 MT22 後未同步更新 AgentSession 相容層」）。

---

## 9. 安全紅線與 AgentX Shell 規範

- 禁止：
  - 直接 `rm -rf` 重要目錄（尤其是 .agentx/、src/、tests/）未經確認。
  - 編輯自身核心（bootstrap, registry, loop, cli）時不先讀 AGENTX.md。
  - 繞過工具 sandbox 寫入 workspace 外。
  - 在無 approval 情況下執行高風險工具（尤其是 write/edit 自身程式碼時）。
- 所有危險操作需「先解釋再執行」，經人類同意後才動手。
- **Self-Modification 特別紅線**：修改 AGENTX.md 時必須遵守 §0.6 自修改協議 + 跑測試 + commit。

AgentX Shell 三大原則：
1. 含 destructive 效果的命令只能提案，不得直接執行。
2. 跨 workspace 操作必須遵守 sandbox。
3. 多路徑命令應拆成單一路徑逐一處理。

變更等級：
- GREEN（只讀工具）可自由執行。
- YELLOW（可逆編輯）需回報。
- RED（不可逆 / 改核心 / 改 AGENTX.md 結構）需簽核與明確確認。

---

## 10. Profile、專案地圖與按需載入文件

- **本專案 Profile**：agentX 開發者模式 — 強調整潔架構、MT22 統一、Headless 可靠性、AGENTX.md 自演進。
- **按需載入（遇到情境時先讀對應文件）**：
  - MT22 相關 → `docs/MT22-Migration-Guide.md` + `MT22-Legacy-Removal-Checklist.md`
  - Headless / 優化 → `docs/OPTIMIZATION_ROADMAP.md` + `HEADLESS_OPTIMIZATION_LIST.md`
  - 工具開發 → `src/agentx/tools/builtin.py` + registry.py
  - 記憶 / bootstrap → `src/agentx/bootstrap.py` + .agentx/
  - 自我改進 → 本檔 AGENTX.md § Self-Improvement Protocol

---

## 11. Compact Instructions 規則（agentX 專案版）

當模型壓縮記憶或指令時，必須按以下結構保留關鍵資訊（對齊 CLAUDE.md 9 段 + agentX 特有）：

**1. Primary Request** — 當前 session 的任務目標。

**2. Key Technical Concepts** — 本 session 涉及的關鍵規則：
- MT22 唯一真相來源（tasks.py）
- Headless vs 互動 prompt 分離
- AGENTX.md 自修改協議
- .agentx/ 狀態管理
- 4C 框架、撞牆停手
- Git 規範（中文 commit、逐檔 stage）
- 兩級提示詞（Global CLAUDE.md vs Local AGENTX.md）
- 多代理 review（Codex 強制）

**3. Files and Code** — 本 session 修改/關注的檔案路徑與變更摘要。

**4. Errors and Fixes** — 遇到的錯誤、root cause、修復方式。

**5. Problem Solving** — 已嘗試的方案與決策推理（含 Rejected 方案）。

**6. All User Messages** — 使用者的所有明確指示和偏好（逐條保留，不可省略）。

**7. Pending Tasks** — 未完成的工作項目與阻塞。

**8. Current Work** — 壓縮時正在進行的具體步驟。

**9. Optional Next Step** — 壓縮後應立即接續的動作。

**始終保留的靜態知識**（不受壓縮影響）：
- AGENTX.md 核心原則與自修改協議
- MT22 唯一真相來源
- .agentx/ 作為專案記憶
- 參考 docs/ 主要指南
- Git 規範
- 安全紅線

---

## 12. 四層北極星 + agentX 開發操作協定

### 四層北極星（改動 / 優化 / 新功能的決策濾網）

| 層 | 目的 | 優先序 |
|---|---|---|
| **L1** | 省 token / 成本 | 表面，次要 |
| **L2** | 去 vendor 綁定（Ollama 模型可替換） | 高 |
| **L3** | 長期存續（.agentx/ 狀態可遷移） | 高 |
| **L4** | **保護開發者注意力**（讓 agentX 開發流程可預期 + 保留 fast path） | **最高** |

**決策規則**：新功能至少打中 2 層才考慮；打到 L4 優先；反 L4 直接砍；L1 單獨打中不足以做。

### agentX 開發操作協定（L4 enforcement）
- 每個非 trivial 任務開場先讀 AGENTX.md + 相關 docs/
- 強制 Codex review（§2）
- 七位/多代理是上限（見 §4）
- 每次重大改動後更新 AGENTX.md（自修改協議）
- Fast Path / 緊急事故 / 人類明確指示「你自己做」→ 豁免

---

## 13. Lab Notes（成敗日誌 — 必保留）

**關鍵失敗模式**（避免重複踩坑）：
- **失敗**：ToolRegistry 仍接受 workspace= kwarg → root cause: MT22 後 registry.py 重構但 cli.py 與 AgentSession 未同步更新。**解法**：統一改用 builtin_tools(workspace, memory) 注入 + 擴充 AgentSession 簽名接受 memory/hooks。
- **失敗**：單一 task.py 假設導致 headless 狀態分裂。**解法**：MT22 強制以 tasks.py 為唯一真相，legacy 自動 migrate + 歷史化測試。
- **失敗**：Headless 直接套用互動 prompt → 過度 reflection、決策猶豫。**解法**：分離 prompt，headless 強調果斷 + 結構化輸出。

**成功路徑**：
- 始終先讀 AGENTX.md + bootstrap + doctor。
- 小步快走 + 完整驗證 + 中文 commit。
- 重大改動必走 Codex review + 更新 AGENTX.md。
- 善用 .agentx/handoff/ 記錄即時決策。

**2026-06 Tsumu 四大架構改善 (hooks / unified error / file tracking / JSONL persistence) + 後續 landing 修正**：
- **失敗模式暴露**：把 learning 移到 hooks 後，coordinator/plan_mode 等使用多 session 的地方 response 預算爆炸；ShellState 瘦身後舊測試 ctor 崩；GREEN 裡不小心放了執行型 npm test / vitest（Codex 抓到）。
- **解法**：學習 hook 在 coordinator/plan 測試明確 disable；_state 動態 attach + module-level testable cmd/dispatch shim 維持相容；npm test 類移到 BUILD_COMMANDS (YELLOW)；registry 支援 _return_effective 讓 file tracking 看到 hook rewrite 後的 args；SESSION_END 也在正常 final 發；fork 先驗證再寫檔；error_details 真的填；Fake 全部接受 **kwargs 防未來。
- **Codex review**：已產生 docs/CODEX-REVIEW-TSUMU-ARCH-2026-06.md 並實際呼叫 codex-cli 跑過，High 項目（GREEN 安全、hook args 一致性、SESSION_END 完整性、post hook 掉 error 欄位）已修；Medium 多數已處理或加 comment。
- **教訓**：新 hook/persistence 機制改變 side effect 數量與狀態重建，測試必須用 disable 或 defensive fakes，而非硬算 call count。重大架構必 Codex +  landing fixes 才算完成。

**2026-06 Edit-Verify Micro-Loop 強化 (Option A, Maki 指示)**：
- 發現 insert_code 在所有 prompt（runtime_prompt.py、worker prompt、Gemma delta）與常數（EDITING_TOOLS、_FILE_WRITE_TOOLS、safety.py、recovery.py、context_compactor.py）中被大力推薦用於「精準寫 code」，但 builtin_tools() 完全沒有實作（只有 ghost 引用）。這是寫 code 能力的一個明顯缺口。
- 第一小片：實作 InsertCodeTool（與 EditFileTool 相同安全紀律：resolve_inside_workspace + ensure_safe_write_path + marker 必須出現恰好一次，否則清楚錯誤）。加到 builtin_tools 清單。現有 post-edit 自動驗證（loop.py 492 注入 verify_msg + 583 自動 run_tests + reflection 觸發 + file_ops 追蹤 + persistence state）立即覆蓋它。
- 同時把此方向正式加入 .agentx/tasks.json（id=2, in_progress）。
- ruff clean。
- 新增 focused unit tests for InsertCodeTool（success insert、marker not found、duplicate marker、workspace escape、protected path、registry name resolution），全部通過（使用 auto_approve_yellow=True 繞過 YELLOW gate 測試 tool 本身邏輯，與其他 YELLOW tool 測試模式一致）。
- 這直接強化「真正投入寫 code」：現在模型可以合法呼叫 insert_code 做 marker-based 精準新增，而不用總是 write_file 全檔或 apply_patch。現有 post-edit 驗證（auto run_tests + verify 訊息 + file tracking）自動覆蓋。
- Codex review（codex-cli MCP）給 conditional green：實作概念正確、安全，與 Tsumu pillars 整合良好。主要 Medium 是 __init__.py 未 export InsertCodeTool（已在本 slice 修復） + 建議加 focused unit test（已新增）。Gemini 給明確 green。
- 本 slice 現已處理 Codex 回饋，可視為完成（conditional green 已滿足）。
- Hook-driven verify slice（本動繼續）：實作 _on_post_edit_verify (POST_TOOL_USE listener) 處理 pending_verifies stateful + persist（via append_state） + targeted verify guidance 注入（additional_context 進入 tool result，取代 loop hardcoded verify_msg）。擴充 _restore/_persist/clear/enable 支援 pending_verifies。更新 auto EDITING_TOOLS block 清 pending + 註記 targeted 方向。Hook 註冊於 __init__。測試通過（lifecycle/agent_session/tools）。
- Fixes per Codex (conditional red) + llm-hub (request_changes) + Gemini (green) reviews:
  - EDITING_TOOLS 加入 canonical "edit_file", "write_file"（search_replace alias 由 registry primary 解析，listener 也 normalize 處理；write_file 現在正確觸發）。
  - pending_verifies clear 移到 test verification 之後（edit 時仍 stateful，供 resume；解決 model 指示與實際行為矛盾）。
  - Hook 訊息更新，明確說明本 slice auto test + clear 行為。
  - 新增 duplicate registration guard（_post_edit_verify_registered，類似 learning hooks）。
  - apply_patch 因無 path 自然 skip pending（留在 EDITING_TOOLS 供 auto test）。
  - 無新 test（現有 47 pass 涵蓋；未來補 focused）。
- 後續（若需）：更積極 targeted（ruff per path 而非全 run_tests）、auto read-back snippet 作為 additional_context、更新 prompts 提及 hook verify、加 unit test for pending state。
- Evidence：git diff + ruff clean + pytest 47 pass。準備 re-briefing 給 Codex re-review。
- 符合 AGENTX.md：小步 + 4C + 更新 tasks + 記 Lab Notes + 為 Codex 準備內容 + 回應 review 發現。

---

## 14. Compact Instructions 結構（當需要壓縮時使用）

（見 §11，完整 9 段 + 靜態知識保留清單）

---

**始終保留的靜態知識**（不受壓縮影響）：
- AGENTX.md 自修改協議（§ Self-Improvement）
- MT22 唯一真相來源（tasks.py / .agentx/tasks.json）
- .agentx/ 作為專案記憶與狀態系統
- 兩級提示詞（Global CLAUDE.md vs Local AGENTX.md）
- 強制 Codex review + Git 規範（中文 commit）
- 安全紅線（特別是 self-modification 時）
- 參考文件清單（docs/MT22-*.md 等）

---

當你在 agentX 專案內工作時，請將本檔視為最高優先的 Local 規則來源。讀完後若有新洞見，請主動更新本檔，讓未來的自己（或其他 agentX 實例）受益。

**End of AGENTX.md**

---

## Appendix: Inspiration from ai-tetsu (Sister Project Patterns)

agentX 與 ai-tetsu（/Users/maki/GitHub/ai-tetsu）是 Maki 的兩個姊妹實驗：
- VirtualMe（ai-tetsu 姊妹）負責「捕捉你是誰」（人格憲法、VirtualMe 八維訪談為 source-of-truth）。
- ai-tetsu 負責「會學你、替你做事、越用越懂你但不漂移」。
- agentX 是「本地工程 agent shell 工具本身」——我們開發 agentX 時，應借鏡 ai-tetsu 的成熟模式來強化 agentX 自身的「kernel 紀律」與自演進。

### 從 ai-tetsu 借鏡的核心模式（必須內化到 AGENTX.md 實踐）

1. **Kernel = 決策矩陣的實體化**（ai-tetsu kernel blueprint v1 RATIFIED）
   - agentX 的 kernel = 把「該有的能力」實體化成器官，每個器官對應一條能力矩陣 row。
   - 定義 agentX kernel 器官（對齊現有架構）：
     - Context Bootstrap（載入 AGENTX.md 優先 + .agentx/ + docs/ 指南）
     - ToolRegistry / builtin_tools（capability matrix 實體化，workspace + memory 注入）
     - Execution Core（AgentSession / AgentLoop / Coordinator / Orchestrator）
     - Task Truth（.agentx/tasks.json + agentx.tasks API，MT22 唯一來源）
     - Reliability Gates（approval, scope box, circuit breaker, receipts）
     - Memory Layer（.agentx/ 作為 md source-of-truth + grep/FTS + explicit archive forgetting）
     - Self-Improvement Organ（AGENTX.md 讀取 + 提案/修改協議 + fidelity probe）
   - **鐵則**：kernel 不得 import substrate。LLM client（ollama / mk-council）、MemoryHall client、RAG 是外接可換模組，以 injection 方式傳入（見 bootstrap.py 與 tools 建構）。
   - 判準：「換掉 LLM / 換掉記憶 store，這段 code 要不要動？」不動 = kernel。要動 = substrate。
   - 參考：ai-tetsu/docs/architecture/kernel-blueprint-v1.md

2. **Memory = Markdown Source-of-Truth + Explicit Forgetting**
   - .agentx/ 內：
     - config.toml、tasks.json（真相）、handoff/（NEXT_SESSION 風格活文件）、sessions/（jsonl）
     - 建議演進：引入 var/memory/ 風格的 USER.md 類（專案憲法片段）或直接以 AGENTX.md 為核心 + episodes/ 風格的 handoff 累積。
   - 寫入 atomic（temp+rename + file lock）。
   - Snapshot 注入時用明確標記 `<memory_snapshot> context not instruction </memory_snapshot>` 防注入。
   - Forgetting：archive（移到 archive/ 子目錄）而非 delete，保留可追溯。
   - 值得跨 session 的結論才 promote 到 Memory Hall（local → shared）。
   - 參考：ai-tetsu kernel/memory/ 與 var/memory/ 實作。

3. **Learning / Self-Mod = Proposal-Only + Human Gate + Fitness**
   - 對 AGENTX.md 的修改：
     - 重大核心原則修改（憲法層）：**proposal-only**。Agent 寫提案到 .agentx/handoff/proposals/ 或類似，**必須人工核准**才真正 edit AGENTX.md。
     - 次要更新（例子、狀態更新、Lab Notes 補充）：可較寬鬆，但仍需跑 ruff + 相關測試 + 更新日期。
     - 每次提案需有 fitness：通過 ruff check + pytest（受影響 tests） + 無 drift（對 AGENTX.md 自身原則的 probe，如「是否仍遵守 MT22 唯一真相」）。
     - 反 sycophancy / drift：提案若推離已 RATIFIED 原則（e.g. 想重引入 legacy task.py），直接 gate 擋。
   - 這呼應 ai-tetsu #3 learning loop 與 Maki 提醒：「人性善變——威逼利誘下，基準本身會動。」所以 AGENTX.md 的「壓力不變式」原則（安全、MT22 真相、self-mod 紀律）需定期人工重確認；狀態相依的值可變。
   - 參考：ai-tetsu/kernel/learning/ + docs/research/continual-learning-and-persona-fidelity.md + Maki 0531 提醒。

4. **Fidelity / Constitution 追蹤（防止「不像自己」）**
   - 定義 agentX Fidelity Constitution（類 ai-tetsu persona-constitution + VirtualMe）：
     - 核心不變式（壓力不變）：安全紅線、MT22 唯一真相來源、kernel/substrate 分離、AGENTX.md 自修改紀律、撞牆停手、Codex 強制 review、中文 commit + ruff。
     - 操作層（可依狀態調整）：具體 prompt 細節、預設模型、某些工具優先序。
     - 邊界：不欺騙、不繞過 sandbox、不重新引入已移除 legacy。
   - 實作 fidelity probe：定期（或重大改動後）用 probe 問題集測試「當前 agentX 實作是否仍忠於 AGENTX.md 原則」（類 ai-tetsu 27 題 fidelity question bank + ACC/IC/RC_atom 計分）。
   - 量測 drift vs baseline shift：如果原則「看起來漂了」，先問「是專案自己變了（Maki 決策）還是實作 drift？」——定期人工重跑「VirtualMe 式」捕捉（重訪談或重確認原則）。
   - 參考：ai-tetsu/docs/architecture/persona-constitution-v1.md + fidelity-probe-v0.md + fidelity-question-bank-v1.md + atomic-persona-evaluation。

5. **Rules Layer（確定性 guardrail 先於 LLM）**
   - 像 ai-tetsu rules.py：開發流程中先跑確定性 rules（ruff check、pytest 相關、no legacy reintro 靜態檢查、AGENTX.md 一致性 scan、bootstrap 載入測試）。
   - 只有 rules_layer 通過後，才讓「LLM 判斷」（或 agent 決策）進行。
   - 範例 rules（可實作在 scripts/ 或 Makefile）：
     - 若偵測到 src/agentx/task.py 殘留 → CRITICAL。
     - AGENTX.md 未包含最新 RATIFIED 原則 → WARNING。
     - 無對應測試的重大工具改動 → WARNING。
   - 這保護「學習但不亂學」。

6. **NEXT_SESSION.md / Handoff 風格活文件**
   - .agentx/handoff/ 應維持 NEXT_SESSION.md 風格（RATIFIED 原則清單、當前狀態、已達成、阻塞、下一步、memhall 引用、session dir 引用）。
   - 每次重大 session 結束更新它，作為「從哪裡接續」的指標。
   - 參考：ai-tetsu/NEXT_SESSION.md（含 Maki 提醒升格為設計原則）。

7. **Council 決策 + Evidence 追蹤**
   - 重大架構/原則變更，建議用多代理 council（Codex Engineer + Gemini Analyst + Grok Build 平行 + human ratify），產出帶 evidence 的 decision record，寫入 AGENTX.md + docs/ + handoff。
   - 所有 RATIFIED 決策必須有 evidence 引用（session dir / memhall entry / PR / test）。

8. **.claude/ 與本地設定**
   - ai-tetsu 用 .claude/settings.local.json 控制 permissions（例如 allow 特定 skill）。
   - agentX 開發時，可在 .claude/ 放專案本地設定（e.g. 允許 wrap-up skill、特定 tool 權限），但核心規則仍由 AGENTX.md 驅動。
   - 參考：ai-tetsu/.claude/settings.local.json。

### 如何在 agentX 開發中實踐這些（行動清單）
- 每次開工前：讀 AGENTX.md + .agentx/handoff/NEXT_SESSION.md（如果存在） + `agentx doctor`。
- 重大改動：先寫 proposal 到 handoff/proposals/，跑 rules_layer（ruff + tests + fidelity probe 草稿），人工核准後才 edit 核心。
- 記憶寫入：優先本地 .agentx/ md，值得的才 promote Memory Hall。
- 改進 AGENTX.md 本身：視為最高優先的 self-improvement 器官，更新後跑驗證（bootstrap 載入測試 + 相關 unit tests）。
- 追蹤 fidelity：定期用 probe 驗證「當前實作是否仍忠於本檔原則」。
- 借鏡 ai-tetsu 時：明確引用其 docs/architecture/ 作為參考，並在 AGENTX.md 記錄「此原則從 ai-tetsu 移植，evidence: [session]」。

這些模式讓 agentX 在開發自己時，也能達到 ai-tetsu 追求的「會學、會變，但不會失去自我（設計原則）」。

**End of Appendix**

---

**當你在 agentX 專案內使用 agentX 時，請將本檔（含 Appendix 借鏡 ai-tetsu）視為最高優先 Local 規則。讀完後若有新洞見或從 ai-tetsu 學到新模式，請主動更新本檔。**
