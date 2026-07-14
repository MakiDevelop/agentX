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

## Repo-local instructions（AGENTX.md）

agentX 支援類似 `CLAUDE.md` / `AGENTS.md` 的 repo-local instructions。任何 repo 根目錄都可以放：

- `AGENTX.md`：agentX 原生規則檔，最高優先。
- `AGENTS.md`：通用 agent 規則檔，相容既有 Codex / agent repo。
- `CLAUDE.md`：Claude 相容規則檔，方便沿用既有專案文件。

啟動 `ax` 時，agentX 會依 `AGENTX.md > AGENTS.md > CLAUDE.md` 的順序讀取這些檔案，並把內容放進 repo bootstrap context。這些檔案是專案內 guidance，不能覆蓋 agentX 的安全政策、approval policy 或不可逆操作紅線。

本專案根目錄也有 `AGENTX.md`，這是 agentX 開發自身時的主要指令與規則文件。

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
agentx -p "幫我看 repo" --agent --model gpt-oss:20b
agentx -p "幫我看 repo" --agent --backend llama_cpp --model local-model
agentx -p "幫我看 repo" --agent --base-url http://127.0.0.1:8081
agentx -p "幫我看 repo" --agent --timeout 180
agentx -p "幫我看 repo" --agent --run-timeout 300
agentx -p "幫我看 repo" --agent --workspace /path/to/repo
agentx -p "幫我看 repo" --agent --approval auto-approve
agentx -p "幫我看 repo" --agent --quiet
agentx -p "幫我看 repo" --agent --dry-run --json
agentx -p "幫我看 repo" --agent --result-output .agentx/results/run.json --quiet
agentx -p "幫我看 repo" --agent --result-output .agentx/results/run.jsonl --result-output-format jsonl
agentx --list-backends
agentx --list-models --json
agentx backends --json
agentx models --backend llama_cpp --base-url http://127.0.0.1:8081
agentx --version
agentx version --json
```

外部傳入 prompt，類似 `claude -p`：

```bash
agentx -p "只回一句話：你是什麼？"
axp "只回一句話：你是什麼？"
agentx --prompt-file briefing.md --agent --output-format json
agentx --workspace /path/to/repo --prompt-file briefing.md --agent --output-format json
cat briefing.md | agentx --stdin --agent --output-format json
```

需要 agent 工具模式：

```bash
agentx -p "幫我列出這個 repo 的檔案" --agent
```

複雜任務可先規劃再執行；`--plan-then-execute` 會在同一個 headless session 內先跑 plan-only，再切到 execution：

```bash
agentx -p "重構 headless session resume" --agent --plan-then-execute
agentx ask "重構 headless session resume" --plan-then-execute
```

需要給 CI、script 或其他 agent 讀取時，可輸出結構化 JSON：

```bash
agentx -p "幫我列出這個 repo 的檔案" --agent --json
agentx -p "幫我列出這個 repo 的檔案" --agent --output-format json
agentx -p "幫我列出這個 repo 的檔案" --agent --output-format jsonl
agentx ask "幫我列出這個 repo 的檔案" --json
agentx ask "幫我列出這個 repo 的檔案" --output-format json
agentx ask "幫我列出這個 repo 的檔案" --output-format jsonl
agentx ask "幫我列出這個 repo 的檔案" --result-output .agentx/results/ask.json --quiet
```

JSON payload 會包含 `schema_version`、`output`、`exit_code`、`termination`、`failing_tools` 與 `stats`。
`stats` 目前包含 message count、粗估 context tokens、model turn count、tool call count、reflection count、error count、compaction count、pending verifies 與 task counts。
`log_summary` 會提供精簡可機讀執行摘要：termination、tool outcomes、successful/failing tools、recent errors、recovery suggestions、pending verifies 與 deterministic `handoff_summary`。
`--output-format jsonl` 會輸出單行 event envelope，例如 `{"event":"result","data":{...}}`；dry-run、version、backends、models 會分別使用 `dry_run`、`version`、`backends`、`models` event。
`--result-output PATH` 可把同一份 result payload 寫成 workspace 內 artifact，plain stdout 時預設寫 JSON，`--output-format jsonl` 時寫 JSONL event；路徑拒絕 workspace escape 與覆蓋既有檔案。需要 artifact 格式和 stdout 格式分開時，可用 `--result-output-format auto|json|jsonl`。
穩定欄位契約見 [`docs/HEADLESS_PAYLOAD_CONTRACT.md`](docs/HEADLESS_PAYLOAD_CONTRACT.md)。
使用 `--plan-then-execute --json` 時，payload 會額外包含 `phases`，分別提供 `plan` 與 `execution` 的輸出，方便上游 agent 或 script 解析。

長任務需要跨 headless run 接續時，可保存並恢復 agent session：

```bash
agentx -p "先讀 repo 並整理下一步" --agent --save-session --json
agentx -p "照上一輪下一步繼續" --agent --resume-session latest --save-session --json
agentx ask "照上一輪下一步繼續" --resume-session latest --save-session --json
```

`--resume-session` 只會讀取目前 workspace 的 `.agentx/sessions/*.session.jsonl`；JSON payload 的 `session_path` 會回報實際保存或恢復的 session 檔，`log_summary.handoff_summary` 也會在可用時附上 `resume_session` 與可複製的 `resume_command`。Resume 會還原關鍵 runtime state，包括 tool outcomes、file ops、pending verifies、termination 與 observability counters。
已保存的 JSON/JSONL payload 可用 `agentx handoff-inspect PATH` 抽出接手資訊，例如 resume command 與 recovery checklist；script 可用 `--field resume_command --next-prompt "照上一輪繼續"` 只取可直接執行的續跑命令，也可用 `agentx ... --output-format jsonl | agentx handoff-inspect - --field resume_command` 走 stdin pipeline。需要讓 wrapper 同時感知原 headless run 的失敗或 timeout 時，加上 `--use-payload-exit-code`，會先輸出接手資訊再用 payload 的 `exit_code` 結束。需要把 artifact 當成接手 gate 時，加上 `--require-handoff`，若沒有 `needs_handoff=true` 與 `resume_command` 會 exit 1；加上 `--require-schema-version` 可拒絕舊版或未知 payload contract。
需要穩定 artifact path 給 CI 或其他 agent 時，可用 `--session-output PATH` 指定 workspace 內 JSONL 檔；它會隱含開啟 session persistence，且拒絕覆蓋既有檔案：

```bash
agentx -p "先讀 repo 並整理下一步" --agent --session-output .agentx/sessions/briefing.session.jsonl --json
agentx ask "先讀 repo 並整理下一步" --session-output .agentx/sessions/briefing.session.jsonl --json
```

`-p --agent` 與 `ask` 都支援 `--max-steps` 來限制 agent loop 步數。

需要隔離長期記憶時，可用 `--no-memory` 關閉本輪 Memory Hall / AMH 讀寫；記憶工具仍會存在，但只回報 disabled/no-op 結果：

```bash
agentx -p "只看目前 repo，不讀寫長期記憶" --agent --no-memory
agentx ask "只看目前 repo，不讀寫長期記憶" --no-memory
```

Headless exit code：

- `0`：成功或一般回答
- `1`：任務/工具/測試明確失敗
- `2`：模型沒有輸出有效工具 JSON、空輸出或 agent 控制流程失敗
- `124`：整輪 headless run 超過 `--run-timeout`
- `130`：請求被取消

`agentx -p --agent` 與 `agentx ask` 會優先使用 `AgentSession` 的結構化結束狀態
（例如 `final_success`、`final_failed`、`max_steps_exceeded`、`direct_tool_failure`）
判斷 exit code；舊的文字分類只作為 fallback。
`--timeout` 控制單次模型 request timeout；`--run-timeout` 控制整輪 headless run deadline，逾時會回 `termination=timeout` 並使用 exit code `124`。

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
| `/find KEYWORD` | 依 keyword 搜尋檔名/路徑與內容，並建議 `/read` 目標 |
| `/where TOPIC` | 依 topic 定位最可能的檔案位置，輸出 ranked `/read` 建議 |
| `/infra [all\|quick\|project\|resource\|home\|vps]` | 讀取專案/資源地圖；`home`/`vps` 會抽取家庭 AI 設施與 VPS 章節，也支援 `家庭AI設施`、`VPS地圖`、`外網主機` 等中文 alias（read-only）。地圖分層與使用規則見 [`docs/RESOURCE_MAPS.md`](docs/RESOURCE_MAPS.md) |
| `/intent TEXT` | 把需求整理成目標、風險、建議讀檔與驗證計畫；SSH/deploy/VPS 需求會附 runtime state pre-flight |
| `/plan-task [--apply] TEXT` | 把需求拆成 checklist；`--apply` 會寫入 `/task` 清單 |
| `/grep PATTERN [PATH]` | 在指定 path 內做內容搜尋；預設整個 workspace |
| `/search PATTERN` | 在 repo 內搜尋文字 |
| `/fetch URL` | 讀取指定外部網頁文字，會阻擋 localhost 與私有網段 |
| `/git [status\|branch\|log [N]\|show [REV]]` | 顯示 allowlisted git 唯讀資訊 |
| `/diff [PATH]` | 顯示 git diff |
| `/stage PATH...` | 逐檔 stage 指定檔案；拒絕 `.`、glob、目錄與 workspace 外路徑 |
| `/unstage PATH...` | 逐檔 unstage 指定檔案，保留 worktree 修改 |
| `/push` | 推送目前 branch 到既有 upstream；不支援參數、force、refspec 或自動 `-u` |
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
memory_backend = "memhall"   # 或 "amh" 以使用官方 AMH / ACA 後端

# amh 後端 store 設定（直接在 config.toml 生效，優先於 env）
# memory_amh_store = "postgres"   # json（預設）、sqlite、postgres、memhall
# memory_amh_path = "postgres://user:pass@host:5432/amh"
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
| `memory_backend` | Memory Hall 後端，`memhall`（預設，舊相容）或 `amh`（官方 Agent Memory Hall，完整 ACA L1-3 治理 + tier/audit 工具）。amh 時可用 `memory_amh_store` / `memory_amh_path` 指定 json/sqlite/postgres/memhall 等不同 store（或用對應 env 覆蓋） |

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

### ACA 符合度與 Memory Backend

agentX 記憶層已逐步對齊 Agent Civilization Architecture（ACA）：

- 寫入自動支援 `tier`（llm_derived / human_confirmed 等）與 `memory_type`
- 提供 `memory_tier_upgrade` 與 `memory_audit` 工具（L2 Trust）
- 透過 `memory_backend = "amh"`（或 `AGENTX_MEMORY_BACKEND=amh`）可切換使用官方 AMH 參考實作，獲得完整 ACA 治理（anti-ouroboros、dedup、provenance 等）

**不同 store 用法範例**（amh 後端）：

在 `.agentx/config.toml` 中：

```toml
memory_backend = "amh"
memory_amh_store = "postgres"
memory_amh_path = "postgres://user:pass@host:5432/amh"
```

或用 env（config 中的值優先，但 env 可覆蓋）：

```bash
# 預設 json store（輕量、本地）
AGENTX_MEMORY_BACKEND=amh ax

# sqlite
AGENTX_MEMORY_BACKEND=amh AGENTX_AMH_STORE=sqlite AGENTX_AMH_PATH="./.agentx/amh/memory.db" ax

# postgres（生產 / 多 agent 共享）
AGENTX_MEMORY_BACKEND=amh AGENTX_AMH_STORE=postgres AGENTX_AMH_PATH="postgres://user:pass@host:5432/amh" ax

# 轉發到既有 memory-hall（搭配 AMH adapter）
AGENTX_MEMORY_BACKEND=amh AGENTX_AMH_STORE=memhall AGENTX_AMH_PATH="http://100.89.41.50:9100" ax
```

預設為 `memhall` 以維持相容性。詳細見 AGENTX.md Lab Notes 與 `docs/`。

## 目前工具

- `list_files`
- `read_file`
- `search_text`
- `git_status`
- `git_diff`
- `memory_search`
- `memory_write`（支援 tier/memory_type 以符合 ACA）
- `memory_tier_upgrade`（ACA L2：llm_derived → human_confirmed）
- `memory_audit`（ACA 事件紀錄）
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
