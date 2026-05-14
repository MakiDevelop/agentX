# agentX

agentX 是一層本地 Ollama agent shell，目標是讓本地 Gemma / Qwen / Llama 類模型具備接近 Claude、Codex、Gemini CLI 的使用體驗：

- 連續互動式 shell
- Ollama 模型切換
- Memory Hall 記憶查詢與寫入
- repo / git / search 工具
- tool-call trace
- JSON tool-call 修復
- repo bootstrap context
- context 狀態與壓縮
- 安全邊界與未來 approval gate

目前還是 read-heavy / guarded MVP，不會讓模型任意執行 shell 或直接改檔。

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
cd /Users/maki/GitHub/agentX
AGENTX_MODEL="${AGENTX_MODEL:-gemma4:e2b}" uv run agentx shell
```

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

目前支援：

| Command | 說明 |
|---|---|
| `/help` | 列出所有 slash command 與中文說明 |
| `/tools` | 列出 agent 模式可用工具 |
| `/context` | 顯示目前 agent context 使用量 |
| `/compact` | 壓縮目前 agent session context |
| `/history` | 顯示本輪 shell 的簡短互動紀錄 |
| `/transcript` | 顯示本輪 JSONL transcript 檔案路徑 |
| `/handoff [TEXT]` | 寫入 Memory Hall 交接摘要 |
| `/files [PATH]` | 列出 repo 檔案 |
| `/read PATH` | 讀取 repo 內指定檔案 |
| `/search PATTERN` | 在 repo 內搜尋文字 |
| `/git` | 顯示 git status |
| `/diff [PATH]` | 顯示 git diff |
| `/memory QUERY` | 查詢目前 namespace 的 Memory Hall |
| `/remember TEXT` | 寫入目前 namespace 的 Memory Hall |
| `/test` | 執行 allowlist 驗證：`ruff check` + `pytest` |
| `/plan` | 切換 plan mode，只討論方案 |
| `/mode chat` | 切到純聊天模式 |
| `/mode agent` | 切到 agent 工具模式 |
| `/models` | 列出 Ollama 目前可用模型 |
| `/model MODEL` | 切換 Ollama 模型 |
| `/status` | 顯示模型、模式、namespace、粗估 tokens |
| `/clear` | 清空 session 並重新載入 repo / memory context |
| `/exit` / `/quit` | 離開 shell |

## 常用流程

```text
/mode chat
你是什麼？

/mode agent
/files
/read README.md
/search Memory Hall
/git
/diff
/test
```

切模型：

```text
/models
/model gemma4:31b
```

寫記憶：

```text
/remember agentX 現在支援 slash command 與 context compact
```

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
- `memory_write`
- `run_tests`

## 安全模型

- GREEN：唯讀操作，自動執行
- YELLOW：可逆變更，後續會接 approval gate
- RED：破壞性或敏感操作，禁止或必須 Maki 確認

目前不支援任意 shell command，也不會讓模型直接改檔。

## 開發驗證

```bash
uv run ruff check .
uv run pytest -q
```

## 下一步

- approval gate
- `apply_patch` 工具
- allowlisted `run_command`
- session transcript JSONL
- 更完整的 context compaction / summary
