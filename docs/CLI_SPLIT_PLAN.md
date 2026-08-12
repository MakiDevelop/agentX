# cli.py 拆分計畫

> 2026-08。取代 `CLI_DISPATCH_REFACTOR_HANDOFF.md` 的做法 —— 那份文件的方向
> （把 slash handler 逐一搬成 dispatch table）在 4 個指令後停住，因為它處理的是
> **shell() 內部的 closure**，那是整份檔案裡耦合最深的部分。本計畫從外圍的
> payload 函式開始，先把容易且安全的體積移走。

## 現況

| | 行數 |
|---|---|
| session 開始（ruff format 前） | 10,761 |
| ruff format 後 | 12,167 |
| 拆出 cli_git.py 後 | 11,681 |

`shell()` 單一函式的 cyclomatic complexity 是 **160**（ruff C901，已標 noqa
並註明「不要再往裡面加分支」）。

## 判斷可拆與否：用工具，不要用猜的

```bash
uv run python scripts/find_closed_groups.py
uv run python scripts/find_closed_groups.py --prefix workflow
```

一個群組**封閉（closed）**的定義：它的呼叫圖遞移閉包不參照 cli.py 頂層的
任何其他名字。封閉的群組可以整段搬走；不封閉的必須先拆接縫。

這件事必須機械判定，因為**憑大小挑會挑錯**：workflow 是最大的家族
（19 個直接函式 / 791 行），看起來最值得先動，但它的閉包會拉進
`command_plan_payload` / `inspect_payload` / `artifacts_payload`，搬走就會
造成循環 import —— 而你會在搬完幾百行之後才發現。

## 已完成

- **cli_git.py**（12 函式 / 454 行）—— git / diff / patch payload。
  0 external，原本連續佔 3306-3793 行。
  cli.py 重新 export 三個對外使用的 payload 函式；私有 helper 留在模組內。

## 建議順序

依「封閉 + 體積 + 群組獨立性」排：

| 順位 | 群組 | 函式 | 行數 | 狀態 |
|---|---|---|---|---|
| 1 | `commit` + `review` | 11 | 387 | 封閉，彼此共用 4 個函式，一起搬 |
| 2 | `trace` + `approval` + `config` + `infra` + `session` | 10 | 230 | 全封閉，小而獨立，可合併成一個模組 |
| 3 | `verify` | 4 | 101 | 封閉 |
| 4 | `artifact` → `doctor` → `gate` | 23 / 26 / 32 | 332 / 400 / 673 | **同一個 cluster**（彼此共用 22-25 個函式），必須當一組處理，不是三刀 |
| 5 | `task` / `objective` / `handoff` | — | — | 只差幾個 module-level 常數（`TASK_STATUS_FILTERS`、`OBJECTIVE_REQUIRED_COMMANDS`、`HEADLESS_PAYLOAD_SCHEMA_VERSION`），把常數一起搬即可封閉 |
| 6 | `workflow` / `inspect` / `next` / `reliability` | 44-99 | 1000-2900 | 互相共用 44-60 個函式，是最大的糾纏團。要先把 `command_plan` / `artifacts` / `inspect` 的接縫抽成獨立模組 |
| 7 | `shell()` 本體 | 1 | 1,254 | 最後處理。所有 slash handler 都是 closure over local state，`ShellState` 目前不是單一真相來源（Codex P1，見舊 handoff） |

## 每一刀的作法

1. `uv run python scripts/find_closed_groups.py --prefix <家族>` 確認封閉
2. 整段搬到 `src/agentx/cli_<家族>.py`，補 import，加 `__all__`
3. cli.py 重新 export **外部實際會用到的**名字。私有 helper 不要 re-export
   —— 先實查 src/tests/scripts 有沒有引用（注意 `_git_read` 這種名字會誤命中
   `test_handle_git_readonly_subcommands` 這類函式名，要看實際 import 而非
   字串命中）
4. 在同一個 commit 調低 `tests/test_cli_module_size.py` 的 `MAX_CLI_LINES`
5. 驗證：`ruff check` + `ruff format --check` + `pytest` + coverage 地板

## 不變式

- `tests/test_cli_module_size.py` 的 ratchet 只准往下修
- 其他模組不得超過 1,600 行 —— 把 cli.py 拆成幾個一樣大的檔案沒有意義
- 抽出的模組不得 import 回 `agentx.cli`（有測試用 AST 守）
- Typer command 函式留在 cli.py。搬的是 payload / format / 純資料函式
