# agentX vs 七位一體

> 整理日期：2026-05-18

> 2026-05-25 補註：目前 repo 內 `AGENTS.md` 採用 A5X-G 五位操作角色（Maki / Claude / Codex / Gemini / Perplexity）。本文保留「七位一體」語境，是因為早期治理框架曾把 Local Brain（gemma4）與 SuperGrok 額外列為獨立席位。閱讀時請把本文視為「agentX 與多 agent 治理框架的關係」說明，而不是目前 repo 的角色清單規範。

## 一句話總結

**agentX 是一個「讓本地模型好用」的工具；七位一體是一套「調度一群跨供應商專家」的協作協定。**

兩者根本不是同一個範疇——一個是可執行的軟體，一個是治理框架。

---

## 對照表

| 面向 | agentX | 七位一體 |
|---|---|---|
| 本質 | 軟體工具 / CLI runtime（`~/GitHub/agentX`） | 自建的協作框架 / 治理協定 |
| 形態 | 可安裝、可 `ax` 啟動的 repo | 規則文件 + 路由習慣，買不到也跑不起來 |
| 參與者 | 單一本地模型（Gemma / Qwen / Llama，可切換） | 七個角色：Maki、Claude、Codex、Gemini、Perplexity Max、gemma4:31b、SuperGrok |
| 供應商 | 全本地 Ollama，零雲端依賴 | 跨七家不同供應商，刻意去綁定 |
| 進程模型 | 一個 shell、一個 session、一個模型 | 多 agent 並行（上限 3-5），檔案 I/O 協作 |
| 通訊機制 | shell 內 tool call / slash command | 三層分離：MCP / CLI+檔案 I/O / API |
| 治理 | GREEN/YELLOW/RED 三級安全模型 | Council Protocol、風險分級、強制異議、evidence 引用 |
| 解決的問題 | 「讓本地小模型也有 Claude CLI 體驗」 | 「一個任務該派給哪個 agent、怎麼派」 |

---

## 三個關鍵分歧點

### 1. 工具 vs 協定
agentX 是你能 `uv sync` 安裝、能讀 source code、能 `ax` 啟動的具體軟體——有 cli.py、loop.py、30 多個 slash command。七位一體你裝不起來——它是 CLAUDE.md §4/§13 描述的一套規則、路由決策樹和檔案協作流程。

### 2. 一個本地腦 vs 七個角色
agentX 同一時間只跑一個本地模型，設計目標是讓單兵 Gemma/Qwen/Llama 夠好用——不對外、可離線。七位一體刻意是七個跨供應商角色，各有守備範圍：Claude 當 Architect、Codex 當 Engineer、Gemini 當 Analyst、兩個 Scout、Maki 當 Chair。它的價值正來自「不要把事情全壓在一個 agent 上」。

### 3. 使用體驗 vs 路由決策
agentX 回答「本地模型怎麼用得順」——連續互動 shell、tool-call trace、JSON 修復、context 壓縮。七位一體回答「這件事該誰做」——routing 決策樹、agent 守備範圍、撞牆停手、evidence 綜合。

---

## 真正的關係：包含，不是對立

兩者不是競品。七位一體裡有一個席位叫 **gemma4:31b（Local Brain）**，負責簡單任務、隱私資料、背景批次、離線推論。

**agentX 正是「把 Local Brain 這個席位做成好用工具」的實作。** 七位一體在協定層定義「該有一個本地腦」，agentX 在工具層提供「本地腦的操作介面」。你在 agentX 裡跑 gemma4:31b，就是在用七位一體的第六個座位。

agentX 已接上 memhall（Memory Hall 查詢/寫入），呼應七位一體那座共用記憶大廳——只是用單 namespace 的方式。

---

## 為什麼不衝突

七位一體的設計哲學是「四層北極星」，依優先序：

- **L1 省成本** — 表面動機，次要
- **L2 去供應商綁定** — 任何單一供應商都必須是可替換零件
- **L3 長期存續** — 即使明天某家 AI 公司倒了，系統仍能跑
- **L4 保護注意力**（最高）— 把人的注意力投回寫作、思考、產品決策、家人

agentX 全本地、零雲端，天生強打 L2 和 L3——它就是一個「不依賴任何雲端供應商也能跑的本地腦」。但 agentX **不解決 L4 的路由問題**：它不管「該派給誰」，只管「本地那一位做得順」。

所以兩者疊起來才完整：七位一體決定「誰做」，agentX 讓「本地那一位」做得順。agentX 把七格中的一格做強了，另外六格（雲端 Architect、Engineer、Analyst、兩個 Scout、Chair）以及它們之間的路由紀律，agentX 不涵蓋、也不打算涵蓋。

---

## 給對方解釋時可以用的精簡說法

> agentX 是一個工具——一層本地 Ollama agent shell，目標是讓 Gemma/Qwen 這類本地模型有接近 Claude CLI 的體驗，全本地、可離線。七位一體不是工具，是一套協作協定：把七個來自不同公司的 AI 當成透明專家，由人當主席來調度。兩者不是競品——七位一體裡有一格叫「本地腦（gemma4:31b）」，agentX 正是那一格的載體。七位一體決定「誰做」，agentX 讓「本地那一位」做得順。
