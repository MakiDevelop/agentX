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

用 `/tools` 看工具與風險分級：

```text
/tools
```

用 `/workflows` 看常用路徑：

```text
/workflows
```

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
