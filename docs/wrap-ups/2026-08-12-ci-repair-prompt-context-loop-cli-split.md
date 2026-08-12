# 2026-08-12 CI 修復 + Prompt/Context/Loop 工程 + cli.py 拆分

> 範圍：治理與 CI / Prompt-Context-Loop 三層 / cli.py 結構
> Risk：無 production 影響（本 repo 為本機開發工具）
> Outcome：CI 從連續 7 次紅轉綠；15 個已知漏洞清零；cli.py 12,167 → 10,796 行

## 觸發點

Maki 要求檢視 repo 並提出可優化項目，取得同意後逐一處理。
中途追加目標：「讓 agentX 像 Claude Code 一樣，只是可以用地端模型，
所以要把 Prompt / Context / Harness / Loop Engineering 做到完善」。

## Root cause / 動作 / 修法

### 起點：CI 壞了一個月

`gh run list` 顯示 2026-07-15 起連續 7 次 push 全紅，每次 ~13 秒即掛。
Root cause 是 `ci.yml` workflow-level `env: UV_EXCLUDE_NEWER: "2d"`——
相對 span 每次呼叫算出新的絕對時間戳，uv 認定 lockfile 在不同 resolver
setting 下產生 → 重新 resolve → 所有 `--frozen` / `--check` 必敗。

因此 ruff 與整套測試一個月沒在 CI 執行過，底下累積了：

| 問題 | 數字 |
|---|---|
| pypdf 已知漏洞 | 15（pip-audit 自己也壞了，2.4.0 import 現代 cyclonedx 已移除的模組） |
| 未 ruff format 檔案 | 83 |
| 環境相依測試失敗 | 13（ripgrep 未安裝 8 個、終端寬度/顏色 5 個） |

### 反覆出現的 bug class：手寫文件與機器可讀真相脫節

本 session 遇到三次：

1. `safety.py` 風險表無 production 呼叫點，33 個 tool 有 6 個分類不符
   （`write_file` / `edit_file` 被標成 RED）
2. system prompt 工具清單漏教 11 個註冊工具，且散文叫模型
   「一律用 write_file」但清單沒有它的定義
3. README 只寫了 51 個 CLI 命令中的 46 個

三次都靠人工比對發現 → 寫 `scripts/check-docs-drift.py` 讓它變紅燈。

### Prompt / Context / Loop 三層各修一個實測問題

| 層 | 問題 | 數字 |
|---|---|---|
| Prompt | 手寫工具清單漂移 | headless prompt 教 22/33 → **33/33** |
| Context | `chars//4` 對中文低估 | **2.6×**，壓縮永遠在爆掉後才觸發 |
| Loop | 工具輸出無上限 | 一次失敗 pytest = **18,476 tokens**（8k 視窗兩倍多） |
| Loop | 終止分類錯誤 | `max_steps` 用盡卻回報「模型不會輸出 JSON」並建議換模型 |

## 改動清單

- `src/agentx/safety.py` 104→31 行，只保留 `Risk` enum
- `src/agentx/proc.py` 新增，統一 subprocess 環境（locale 固定），29 個呼叫點 27 個改走它
- `src/agentx/tokens.py` 新增，script-aware token 估算 + 模型回報值校準 + 頭尾保留式截斷
- `src/agentx/benchmark.py` 新增，本地模型可靠性基準
- `src/agentx/runtime_prompt.py` `build_tools_section()` 取代手寫清單，三條 prompt 路徑共用
- `src/agentx/ollama.py` 開始記錄 `prompt_eval_count`（原本丟棄）
- `src/agentx/loop.py` 終止分類 + 工具輸出截斷
- `src/agentx/cli_git.py` / `cli_output.py` / `cli_verify.py` / `cli_artifacts.py` 新增
- `tests/conftest.py` 新增，固定算繪環境
- `pyproject.toml` ruff 13 類規則 + C901 ratchet + coverage 地板 + `[tool.uv] exclude-newer`

## 驗證

```
CI            綠（最近 3 次 success）
tests         1065 collected，全綠（起點 983，其中 1 紅）
coverage      branch 71.95%（地板 71）
ruff          check + format 全綠
docs drift    51/51 CLI 命令同步
pip-audit     No known vulnerabilities found
```

prompt 修正 A/B（gemma4:31b）：`expectation_match` **0.636 → 0.818**。

## Open issues / Follow-up

1. cli.py 拆分未完，剩 5 刀 — 見 `docs/CLI_SPLIT_PLAN.md`
2. `orchestrator.py` 0% coverage（219 statements，`NEXT_SESSION.md` 列為 kernel 器官）
3. `max_steps` 預設 8 是否太低（未動，涉及成本）
4. `ask()` 仍 393 行 / 複雜度 37，未拆成 step handlers
5. UP042 StrEnum 遷移（已刻意 ignore 並註明理由）

## 參考

- AMH: `01KZTPDBYM0S8WYCW5GNB1KHT5`（episode）/ `01KZTPBC0VWSNNKA98847JNB48`（state）
- 交接包：`~/Documents/agent-council/2026-08-12-agentx-hardening-handoff/`（6 檔）
- session dir：`~/Documents/agent-council/2026-08-12-agentx-hardening/wrap-up.md`
- commits：`7841eba` … `18bac6a`（24 個）
