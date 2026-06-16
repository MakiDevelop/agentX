# agentX

**本地 Ollama agent shell**，讓 Gemma / Qwen / Llama 等模型擁有接近 Claude Code、Codex、Gemini CLI 的使用體驗 —— 同時保持你對工具的完整控制與安全邊界。

- 互動式 shell + 三種模式（chat / ask / shell）自由切換
- 內建豐富工具（檔案、Git、測試、Docker、Memory Hall）
- 清楚的風險分級：GREEN 自動、YELLOW 依策略、RED 永遠受保護
- Memory Hall 跨 session 記憶與自動交接（正朝 ACA / Agent Civilization Architecture L1+L2 對齊：source_tier、Anti-Ouroboros 標記、memory_type）
- 上下文壓縮、錯誤恢復、任務清單
- **2026-06 四大架構改善**：lifecycle hooks（SESSION_START/END、FINAL_ANSWER、COMPACT、ERROR 等）、統一錯誤編碼（ToolResult error_type/details）、file ops tracking（compact 後仍保留修改檔案清單）、JSONL session 持久化（enable_persistence / from_session_store / fork_session）
- 支援 llama.cpp OpenAI-compatible 後端（LlamaCppClient，適合本地 gemma4:31b 長程式碼生成）

目前定位為 **read-heavy / guarded MVP**：功能強大，但你永遠握有控制權。

想看產品導覽與五張 vision 圖的對應，讀 [`docs/product-tour.md`](docs/product-tour.md)。

**agentX 的特別之處**：
- 不是把弱模型變成萬能黑箱，而是讓它在明確的安全邊界內可靠地做事。
- 所有關鍵操作都有清楚的風險視覺化（GREEN / YELLOW / RED）。
- 記憶（Memory Hall）與交接是第一級公民，跨 session 工作不會斷線。

想更自主就輸入 `/approval auto-approve`；想最有安全感就保持預設的 ask / strict 模式。

## 2026-06 架構亮點

本次 merge 納入 Tsumu 主導的**四大架構改善**（詳見 docs/CODEX-REVIEW-TSUMU-ARCH-2026-06.md 與 AGENTX.md）：

- **Lifecycle Hooks**：新增 SESSION_START/END、FINAL_ANSWER、TURN_START/END、COMPACT、ERROR 等事件 + HookManager。學習機制已移至 hook listener，便於未來擴展 observability / safety / self-mod。
- **統一錯誤編碼**：ToolResult 新增 `error_type` / `error_details`，ToolRegistry 自動捕捉，loop 優先使用，避免重複分類。
- **File Ops Tracking**：AgentSession 追蹤 read/write 操作，compact 時自動注入 `<modified-files>` / `<read-files>`，讓模型在壓縮後仍知道碰過哪些檔案。
- **JSONL Session 持久化**：SessionStore 支援 append / replay / fork_session。AgentSession 可 `enable_persistence()`，並透過 `from_session_store()` 恢復（包含關鍵 state 如 tool_outcomes、file_ops）。
- **LlamaCppClient**：新增 llama.cpp OpenAI-compatible 後端，針對 gemma4 優化（關閉 thinking、600s+ read timeout、3 次重試、reasoning_content fallback）。
- 其他相容性：edit_file 接受 search_replace alias + old_string/new_string 參數；run_command whitelist 擴充 Node/TS 指令；JSON repair 順序調整；approval config 在 -p / orchestrate / ask 一致讀取。

這些改善讓長任務、本地小模型、session 恢復與自學習更可靠。詳細技術決策與 Codex review 記錄在 `docs/CODEX-REVIEW-TSUMU-ARCH-2026-06.md`。

## 專案自身規則與自學習（AGENTX.md）

本專案根目錄有 `AGENTX.md`，這是 agentX 開發此專案時的**主要指令與規則文件**（類似其他專案的 CLAUDE.md / AGENTS.md）。

- 啟動 `ax` 在這個 repo 內時，agentX 會優先讀取 `AGENTX.md` 作為高優先級 context。
- `AGENTX.md` 內包含：
  - 核心原則（MT22 多任務為唯一真相來源、風險優先、無頭模式行為等）
  - 架構決策與當前狀態
  - **明確的自修改協議**：允許（並鼓勵）agentX 讀取、學習，並使用工具修改 `AGENTX.md` 本身。
- 這讓 agentX 可以在開發自己的過程中持續「學習」並把新規則、新教訓寫回文件中。

貢獻者與未來的 agentX 實例都應該優先參考 `AGENTX.md`。

## 快速開始

```bash
cd /Users/maki/GitHub/agentX
uv sync --extra dev
```

確認 Ollama 已在背景執行：

```bash
ollama list
```

如果 `ollama serve` 顯示 `address already in use`，代表 Ollama 已經在跑，不是錯誤。

## 啟動

最短指令：

```bash
ax
```

等同於：

```bash
AGENTX_WORKSPACE="$PWD" uv --directory /Users/maki/GitHub/agentX run agentx shell
```

`ax` 會使用你目前所在的目錄當 workspace，所以可以在任何 repo 裡直接啟動 agentX。
第一次在某個 repo 啟動時，agentX 會顯示一次 `/guide` 提示；之後可隨時手動輸入 `/guide` 重新查看。

指定模型：

```bash
AGENTX_MODEL=gemma4:31b ax
```

外部傳入 prompt，類似 `claude -p`：

```bash
agentx -p "只回一句話：你是什麼？"
axp "只回一句話：你是什麼？"
```

需要 agent 工具模式：

```bash
agentx -p "幫我列出這個 repo 的檔案" --agent
```

如果目前 terminal 還沒有 `ax`：

```bash
source ~/.zshrc
ax
```

## 三種模式

純聊天，最快：

```bash
uv run agentx chat "只回一句話：你是什麼？"
```

單次 agent 任務：

```bash
uv run agentx ask "幫我列出這個 repo 的檔案"
```

互動式 CLI agent：

```bash
uv run agentx shell
```

## Slash Commands

在 `ax` / `agentx shell` 裡輸入：

```text
/help
```

會列出所有 slash command 與中文說明。

互動式 terminal 支援 slash command 自動補完：

```text
/con<Tab>
/config s<Tab>
```

模型還在回應時，可以繼續輸入下一個一般 prompt。agentX 會把 prompt 放進背景佇列，依序送給同一個 session context。slash command 會等前面已排入的 prompt 完成後再執行，避免同時切模型、清 context 或改 mode。

chat mode 會串流顯示 Ollama 回應；agent mode 的工具 JSON 回合可取消但不串流顯示，避免破壞 tool-call 解析。

互動式 terminal 預設使用底部輸入列與狀態列，並保留一般 terminal scrollback，方便選取與複製文字。

如果想回到 classic prompt：

```bash
AGENTX_TUI=0 ax
```

如果想試 alternate-screen full-screen TUI，可手動開啟：

```bash
AGENTX_TUI=fullscreen ax
```

底部狀態列會顯示目前 model name 與 context 使用率。

對話區會用 `Maki` 與 `agentX` 分隔每輪訊息，避免使用者輸入與模型回覆擠在一起。

chat mode 會明確告訴模型目前正在 agentX CLI 內執行，避免模型把自己誤認成完全不能碰本機的通用聊天機器人。實際能力仍依模式區分：chat mode 只回答；agent mode 與 slash command 才能使用工具。

目前支援：

| Command | 說明 |
|---|---|
| `/help` | 列出所有 slash command 與中文說明 |
| `/guide` | 60 秒快速導覽：模式選擇、常用工作流、安全與記憶 |
| `/workflows` | 列出理解、修改、測試、review、handoff 等實務路徑 |
| `/init` | 掃描 repo 並寫入 project profile 到 Memory Hall |
| `/doctor` | 檢查 Ollama、模型、Memory Hall、git、uv 狀態 |
| `/config` | 顯示目前 agentX 設定 |
| `/config set KEY VALUE` | 寫入 `.agentx/config.toml` 專案設定 |
| `/task [TEXT\|status\|list\|add ...\|update <id> ...\|done <id>\|clear]` | 管理多任務清單 |
| `/tools` | 列出 agent 模式可用工具 |
| `/context` | 顯示目前 agent context 使用量 |
| `/compact` | 壓縮目前 agent session context |
| `/history` | 顯示本輪 shell 的簡短互動紀錄 |
| `/jobs` | 顯示目前 running / queued prompt |
| `/cancel [JOB_ID\|all]` | 取消尚未執行的 queued prompt |
| `/sessions` | 列出最近 transcript 摘要，可搭配 `/resume` |
| `/transcript` | 顯示本輪 JSONL transcript 檔案路徑 |
| `/handoff [TEXT]` | 寫入 Memory Hall 交接摘要，包含建議下一步 |
| `/resume [latest\|FILE]` | 從 transcript 載入最近上下文摘要並顯示載入大小 |
| `/files [PATH]` | 列出 repo 檔案 |
| `/read PATH` | 讀取 repo 內指定檔案 |
| `/attach PATH...` | 把指定檔案內容加入 context，支援拖曳路徑 |
| `/search PATTERN` | 在 repo 內搜尋文字 |
| `/fetch URL` | 讀取指定外部網頁文字，會阻擋 localhost 與私有網段 |
| `/git` | 顯示 git status |
| `/diff [PATH]` | 顯示 git diff |
| `/apply PATCH_FILE` | 套用 workspace 內 patch 檔，需輸入 `yes` 確認 |
| `/approval [ask\|auto\|off\|strict\|auto-approve\|deny]` | 查看或切換 YELLOW 工具 approval policy |
| `/memory QUERY` | 查詢目前 namespace 的 Memory Hall |
| `/remember TEXT` | 寫入目前 namespace 的 Memory Hall |
| `/run COMMAND` | 執行固定 allowlist 命令 |
| `/docker [ps\|build\|up\|logs\|down]` | 執行 workspace 內 Docker Compose allowlist 指令 |
| `/test` | 執行 allowlist 驗證：`ruff check` + `pytest` |
| `/review` | 收集 git diff 與測試結果，輸出 findings-first review |
| `/commit [MESSAGE]` | 跑測試後逐檔 stage、中文 commit 並 push |
| `/plan` | 切換 plan mode，只討論方案 |
| `/execute` | 從 plan mode 切回執行模式 |
| `/mode chat` | 切到純聊天模式 |
| `/mode ask` | 切到單次任務語意的 agent 工具模式，同 `/mode agent` |
| `/mode agent` | 切到 agent 工具模式 |
| `/models` | 列出 Ollama 目前可用模型 |
| `/model [MODEL]` | 查看或切換 Ollama 模型 |
| `/persona [default\|tutor]` | 查看或切換人格設定；`tutor` 是女子大學生家庭教師模式 |
| `/status` | 顯示模型、模式、namespace、粗估 tokens |
| `/clear` | 清空 session 並重新載入 repo / memory context |
| `/exit` / `/quit` | 離開 shell |

維護與排錯：

```text
/guide
/init
/task 建立 agentX task 狀態
/task status
/task done
/doctor
/config
/sessions
```

## 常用流程

```text
/mode chat
你是什麼？

/mode ask
/workflows

/mode agent
/files
/read README.md
/search Memory Hall
/git
/diff
/test
/review
```

佇列管理：

```text
/jobs
/cancel current
/cancel 3
/cancel all
```

吃檔案：

```text
/attach /Users/maki/Desktop/spec.md
/attach ./notes.txt
/attach ~/Downloads/spec.pdf
/attach ~/Downloads/screenshot.png
請根據 /Users/maki/Desktop/spec.md 幫我整理重點
```

也可以把檔案直接拖進 terminal；agentX 會偵測 prompt 內明確出現的檔案路徑並加入該輪 context。文字檔會讀內容，PDF 會抽文字，圖片會加入尺寸與本機 OCR 結果（如果已安裝 `tesseract`）。敏感目錄如 `.ssh`、`.gnupg`、`.secrets` 會略過。

Docker Compose allowlist：

```text
/docker ps
/docker build
/docker up
/docker logs
/docker logs web
/docker down
```

`/docker` 只會使用 workspace 內的 `compose.yaml`、`compose.yml`、`docker-compose.yml` 或 `docker-compose.yaml`。執行前會先印出 final command 與逐參數列表；`build`、`up`、`down` 需要 approval。

外部網頁讀取：

```text
/fetch https://example.com/article
```

`/fetch` 只讀取使用者指定的 `http/https` URL，會阻擋 localhost、`.local` 與私有網段；目前不是搜尋引擎，若要搜尋能力可另外加 `/web search`。

離開 CLI：

```text
/exit
/quit
```

底部輸入列裡也可以按 `Ctrl+D` 離開；`Ctrl+C` 會清空目前輸入。

提交並推送：

```text
/commit 新增 review 審查模式
```

`/commit` 會先跑 status、diff stat、測試，列出逐檔 stage 清單，輸入 `yes` 後才 commit/push。

套用 patch：

```text
/apply patches/my-change.patch
```

接續上一輪：

```text
/resume latest
```

切模型：

```text
/models
/model gemma4:31b
```

切人格：

```text
/persona
/persona tutor
/persona default
```

`tutor` 是女子大學生家庭教師模式：親切、清楚、有耐心，像家庭教師一樣用小步驟與例子說明；仍保持專業與安全邊界。

寫入專案預設值：

```text
/config set model gemma4:31b
/config set namespace project:agentX
/config set mode chat
/config set approval strict
/config set persona tutor
/config set auto_handoff true
```

`/model`、`/mode`、`/approval` 是本輪 shell 立即生效；`/config set` 會寫入 `.agentx/config.toml`，供下次在同一個 repo 啟動時自動載入。
`mode = "ask"` 會正規化成 agent 工具模式；`approval = "strict" | "auto-approve" | "deny"` 會分別正規化成 `ask`、`auto`、`off`。

寫記憶：

```text
/remember agentX 現在支援 slash command 與 context compact
```

## Project Config

每個 repo 可以放自己的 `.agentx/config.toml`：

```toml
[agentx]
model = "gemma4:31b"
namespace = "project:agentX"
mode = "chat"
approval = "ask"
persona = "tutor"
auto_handoff = true
```

載入優先序：

1. 環境變數，例如 `AGENTX_MODEL=gemma4:31b ax`、`AGENTX_PERSONA=tutor ax`
2. 目前 workspace 的 `.agentx/config.toml`
3. agentX 預設值

常用鍵：

| Key | 說明 |
|---|---|
| `model` | Ollama 模型名稱 |
| `namespace` | Memory Hall namespace |
| `mode` | shell 啟動模式，`chat` / `agent`；`ask` 是 `agent` 的 alias |
| `approval` | YELLOW 工具 approval policy，`ask` / `auto` / `off`；也支援 `strict` / `auto-approve` / `deny` aliases |
| `auto_handoff` | 離開 shell 時是否自動寫 Memory Hall handoff |

## 上下文限制

有上下文限制，限制主要來自 Ollama 模型本身的 context window。

agentX 會把以下內容放進 agent context：

- system prompt
- repo bootstrap context
- Memory Hall bootstrap context
- 本輪 shell 對話
- tool call / tool result

查看目前粗估：

```text
/context
```

底部狀態列的 context 百分比用粗估 token 數計算，預設上限為 8192 tokens。可用環境變數調整：

```bash
AGENTX_CONTEXT_LIMIT=32768 ax
```

如果 session 太長或模型開始飄：

```text
/compact
```

或直接重置：

```text
/clear
```

## Session Transcript

每次啟動 `ax` 都會建立一份 JSONL 紀錄：

```text
.agentx/sessions/<YYYYMMDD-HHMMSS>.jsonl
```

在 shell 內查看目前路徑：

```text
/transcript
```

transcript 會記錄：

- session start / end
- slash command
- user prompt
- assistant answer 摘要
- tool result 摘要

`.agentx/sessions/` 已加入 `.gitignore`，不會被提交。

## Session Handoff

agentX 支援 Memory Hall 交接：

```text
/handoff
/handoff 下一輪優先接 apply_patch approval gate
```

如果本輪 shell 有實際 user prompt，退出時會自動寫一份簡短 handoff 到目前 namespace，預設是：

```text
project:agentX
```

自動 handoff 內容包含：

- 時間
- workspace
- model
- mode
- namespace
- transcript 路徑
- 最近互動摘要

關閉自動 handoff：

```bash
AGENTX_AUTO_HANDOFF=0 ax
```

## 目前工具

- `list_files`
- `read_file`
- `search_text`
- `git_status`
- `git_diff`
- `memory_search`
- `memory_write`（支援 tier/memory_type 以符合 ACA）
- `run_command`
- `web_fetch`
- `run_tests`
- `apply_patch`
- `docker_compose_ps`
- `docker_compose_logs`
- `docker_compose_build`
- `docker_compose_up`
- `docker_compose_down`

## 安全模型

- GREEN：唯讀操作，自動執行
- YELLOW：可逆變更，後續會接 approval gate
- RED：破壞性或敏感操作，禁止或必須 Maki 確認

目前不支援任意 shell command；`/run` 只允許固定 allowlist，`/docker` 只允許固定 Docker Compose allowlist。

## 開發驗證

```bash
uv run ruff check .
uv run pytest -q
```

## 下一步

- 更完整的 session resume state reconstruction（目前已實作 tool_outcomes、file_ops、last_failing_tools、compaction_count 等關鍵 state 的 JSONL 快照與還原）
- 擴充 lifecycle hooks 消費者（observability、進階 safety policy、更多自學習策略）
- 繼續優化本地模型穩定性（llama.cpp / gemma4 長任務、thinking mode 控制）
- persona / profile 動態切換與工程人格精煉

詳細架構演進與已解決問題請參考 `docs/CODEX-REVIEW-TSUMU-ARCH-2026-06.md` 與 `AGENTX.md` Lab Notes。
