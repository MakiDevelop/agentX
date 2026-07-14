# agentX Product Tour

agentX 是本地 Ollama agent shell：用 `chat`、`ask`、`shell` 三種入口，把本地模型接上 repo 工具、Memory Hall、測試與交接，同時保留明確的安全邊界。

這份導覽對齊五張產品 vision 圖，目標是把目前 guarded MVP 的八成體驗講清楚，而不是假裝已經有 web UI。

## 1. First Impression

啟動互動式 shell：

```bash
ax
```

第一次在 repo 啟動時會看到一次 `/guide` 提示。之後可隨時輸入：

```text
/guide
/status
/doctor
```

你會看到目前模型、workspace、namespace、mode、approval policy，以及 GREEN / YELLOW / RED 安全姿態。

## 2. Three Modes

```bash
uv run agentx chat "只回一句話：你是什麼？"
uv run agentx ask "幫我找出這個 repo 的測試指令"
uv run agentx shell
```

在 shell 內：

```text
/mode chat
/mode ask
/mode agent
```

`/mode ask` 是面向使用者的命名，實際使用既有 agent 工具模式；`/mode agent` 保留給熟悉內部語意的人。

## 3. Tools And Workflows

外部 runner 第一次接 agentX 時可用 `agentx capabilities --json` 取得 `agentx.capabilities.v1`，一次知道 top-level automation commands、stable schemas、JSONL events、風險、`recommended_entrypoints` 與 `by_schema` 索引。
需要一次拿 runner preflight bundle 時，用 `agentx inspect --json` 取得 `agentx.inspect.v1`；它只讀本機狀態，包含 status、active tasks、sessions、latest approvals、latest traces、diff、capabilities、artifacts、next recommendations、verify command 清單與 command-plan 預檢，並提供 top-level `recommended_command` / `signals` 給簡單 runner 使用，不跑測試或 live probes。
需要 review/commit 前先看機器可讀變更摘要時，用 `agentx diff --json` 取得 `agentx.diff.v1`；`--staged` 看 index，`--patch` 才附 patch text。
需要套 patch 前做安全預檢時，用 `agentx patch-check PATCH --json` 取得 `agentx.patch_check.v1`；它會跑 `git apply --check -`、列出 touched files，並檢查 workspace escape / protected path，但不套用 patch。
需要執行命令前先做政策預檢時，用 `agentx command-plan COMMAND --json` 取得 `agentx.command_plan.v1`；它只判斷 allowlist、YELLOW approval 與 destructive blockers，不執行命令。
需要 deterministic review gate 時，用 `agentx review --json` 取得 `agentx.review.v1`；它會聚合 diff + verify 並輸出 `commit_ready`、blockers、warnings 與 next commands，`--fail-on-blocker` 可供 CI/wrapper 擋流程。
需要 commit 前的機器可讀計畫時，用 `agentx commit-plan --message TEXT --json` 取得 `agentx.commit_plan.v1`；它列出將逐檔 stage 的檔案、review gate 與 blockers，但不會 stage、commit 或 push。
需要單一 runner gate 時，用 `agentx gate --json` 取得 `agentx.gate.v1`；它聚合 review、doctor static 與 latest approvals audit，讓 Codex/Grok wrapper 不必自行拼多個 JSON。
需要決定下一個 runner command 時，用 `agentx next --json` 取得 `agentx.next.v1`；它根據 denied approvals、dirty diff、latest artifacts 與 active tasks 排序推薦下一步，且每個 recommendation 內嵌 command-plan 預檢。
需要在 SSH/deploy/cross-machine 前讀 Maki 的資源地圖時，用 `agentx infra resource-bundle --json` 取得 `agentx.infrastructure_context.v1`；`home` 與 `vps` 會分別抽取家庭 AI 設施與 VPS 地圖，這是 read-only evidence，不是遠端操作授權。
外部 wrapper 可用 `agentx config --json` 取得目前 workspace、model、memory backend、approval、persona 等解析後設定；token 只會顯示 set/missing。
初次接入 repo 時可用 `agentx init --json` 取得 `agentx.init.v1` project profile；預設只讀，加 `--write-memory` 才寫入 Memory Hall。
需要接續工作時可用 `agentx sessions --json` 取得 `agentx.sessions.v1` transcript overview，外部 runner 可依最新 session、approval denied counts 或 transcript path 決定下一步。
需要找 headless artifact bundle 時，用 `agentx artifacts --json` 取得 `agentx.artifacts.v1`，列出 `.agentx/runs` 下的 result/session/handoff 路徑、termination、exit code 與 resume command。
需要審計 YELLOW 操作時，用 `agentx approvals latest --json` 取得 `agentx.approvals.v1`；CI 或上游 agent 可加 `--denied --fail-on-denied`，在輸出 payload 後用 exit code 擋下被拒絕的 approval receipts。
需要看一輪 transcript 發生了什麼時，用 `agentx traces latest --json` 取得 `agentx.traces.v1`，彙整 event/tool counts、tool failures、approval denials、error-like records 與 recent events。
需要讀取長任務狀態時，用 `agentx tasks --json` 取得 `agentx.tasks.v1`；`agentx tasks active --json` 只回 pending / in_progress / blocked，適合接手 agent 決定下一步。
需要跑 repo 驗證時，用 `agentx verify --json` 取得 `agentx.verify.v1`；CI 或上游 agent 可加 `--fail-on-error`，在輸出完整 checks payload 後用 exit code 擋流程。
需要判斷當前 workspace 姿態時，用 `agentx status --json` 取得 version、runtime、git dirty/ahead/behind 與 task counts；這是本機 read-only 狀態檢查，不探測網路服務。
需要健康檢查時，用 `agentx doctor --json` 取得 `agentx.doctor.v1`；CI 或上游 agent 可用 `agentx doctor --static --json --fail-on-error` 只跑本機 `uv`、git、task migration 檢查，失敗時用 exit code 擋下流程。
這些 inspect/catalog/status 類 payload 的欄位契約整理在 `docs/CLI_JSON_CONTRACTS.md`。

用 `/tools` 看工具與風險分級：

```text
/tools
```

Shell 內可用 `/tools git` 或 `/tools YELLOW` 聚焦查看工具；外部 wrapper 可用 `agentx tools --json` 取得同一份 tool catalog 與 GREEN/YELLOW/RED metadata，需要聚焦時可用 `agentx tools git --json` 或 `agentx tools YELLOW --json`。
外部 runner 若已有一個 tool call draft，可用 `agentx tool-plan TOOL --args-json JSON --json` 先確認 canonical tool、risk、approval posture 與基礎 args blocker；它不會執行工具。

用 `/help workflow` 或 `/help /infra` 查單一命令的 usage、examples、risk 與 related commands。
核心 slash command 都有 examples 與 related commands，適合用來快速探索下一步。
Shell 內可用 `/commands memory` 搜尋 catalog；外部工具可用 `agentx commands --json` 取得同一份 machine-readable command catalog，需要聚焦時可用 `agentx commands /workflow --json` 或 `agentx commands memory --json`。
如果輸入錯字，例如 `/wrkflow`，agentX 會提示最接近的候選命令。
外部 runner 可用 `agentx workflows --json` 取得常用 recipe catalog；每個 workflow 會提供 `steps` 與可直接處理的 `commands`，需要單一路徑時用 `agentx workflows headless --json` 或 `agentx workflows audit --json`。

用 `/workflows` 看常用路徑：

```text
/workflows
```

它會列出理解 repo、小步修改、工程驗證、headless bundle/resume、approval audit 與提交收尾路徑。

用 `/workflow headless` 或 `/workflow audit` 可直接輸出單一可複製路徑。

常見工程閉環：

```text
/files
/read README.md
/search Memory Hall
/git
/diff
/test
/review
```

## 4. Memory And Handoff

Memory Hall 是跨 session 延續工作的入口：

```text
/remember agentX 本輪完成了 mode ask alias
/sessions
/resume latest
/handoff 本輪已完成命名對齊，下一輪做 product tour
```

自動 handoff 會包含固定區塊：完成、待辦、阻塞、下一輪建議，方便下一個 agent 或下一輪自己接手。
`/sessions` 會顯示每輪 transcript 的 approval receipt counts，方便快速看出是否有 YELLOW tool 被拒絕；`/transcript approvals latest --denied` 或 `/transcript approvals SESSION --denied` 可以列出本輪、最近上一輪或指定 session 的 approval receipts，並只看拒絕項。外部 runner 則用 `agentx approvals latest --denied --json --fail-on-denied` 做同一件事。

## 5. Safety And Approval

agentX 把安全當成產品功能：

```text
/approval
/approval strict
/approval auto-approve
/approval deny
```

Aliases：

- `strict` -> `ask`
- `auto-approve` -> `auto`
- `deny` -> `off`

GREEN 操作會自動允許；YELLOW 操作依 approval policy；RED 操作永遠受保護。YELLOW tool 的 approval receipt 會寫入 transcript，標示 `auto_approved`、`manual_approved`、`manual_denied` 或 `policy_denied`。`/run` 與 `/docker` 會在執行前顯示 final command 和逐參數列表。
