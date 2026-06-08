# earendil-works/pi 可借鑑清單

> 來源：2026-06-08 七位一體 repo 評估
> 評估報告：`~/Documents/agent-council/repo-eval-20260608-earendil-works-pi/REPORT.md`
> Repo：https://github.com/earendil-works/pi （TypeScript, MIT, 60K+ stars）
> 判決：WATCH + BORROW（不安裝，抄概念）

---

## 1. 供應鏈加固四層防禦（Priority: HIGH） — 已實作

agentX 目前未發布到 PyPI，但若未來發布，這套防禦值得移植為 Python 等價物。

**2026-06 實作狀態**：已針對 uv / Python 環境完成主要四層（見下方「已落地」）。持續追蹤未來 PyPI 發布時的 shrinkwrap-equivalent（constraints + hashes）。

### pi 怎麼做

四個自動化腳本構成四層防禦：

| 層 | 腳本 | 做什麼 |
|---|---|---|
| 1 | `check-pinned-deps.mjs` | CI 掃全部 package.json，任何非 exact version（`^` / `~`）直接 fail |
| 2 | `generate-coding-agent-shrinkwrap.mjs` | 產出 npm-shrinkwrap.json，鎖死 transitive deps |
| 3 | 同上腳本的 allowlist 機制 | 有 install script 的 dep 必須在白名單內，否則 CI fail |
| 4 | `check-lockfile-commit.mjs` | pre-commit hook 防止 lockfile 意外被改 |

另外 `.npmrc` 設 `save-exact=true` + `min-release-age=2`（避免當日發布的包被自動拉入）。

### 已落地（agentX 適配）

- **pyproject.toml**：所有 direct dependencies（含 dev extra）改用 `==` exact pin（不再有 `>=` / `~=`）。
- **uv.lock**：視為 ground truth（等同 package-lock + shrinkwrap）。`uv lock --check` 強制 pyproject 與 lock 一致。
- **scripts/check-pinned-deps.py**：直接 port check-pinned-deps.mjs 邏輯，掃描 pyproject.toml 的 dependencies + optional-dependencies，non-registry（git / url / path）放行，其餘必須是 exact ==pin。
- **scripts/check-lockfile-commit.py**：直接 port check-lockfile-commit.mjs。uv.lock 若被 stage，沒有 `AGENTX_ALLOW_LOCKFILE_CHANGE=1` 就直接阻擋 commit，並印出 review checklist（intentional? age gate? new build-time packages? 先跑 pinned + audit）。
- **.pre-commit-config.yaml**：
  - ruff（lint + format）— 實現 AGENTX.md 原本的承諾。
  - 兩個 local hook 綁定上述兩個 check 腳本。
- **.github/workflows/ci.yml**：push / PR 執行 pinned check、uv lock --check、lock guard script、uvx pip-audit（等同 audit 層）、ruff、快速測試。
- **min-release-age / age gate**：CI 設定 `UV_EXCLUDE_NEWER=2d`（uv 的 --exclude-newer 相對形式，等同 pi 的 min-release-age=2）。本地更新時可 `export UV_EXCLUDE_NEWER=2d; uv lock`。注意 uv 使用的是 exclude-newer 而非 minimum-age 變數。
- **allowlist / lifecycle (layer 3)**：目前以「任何觸及 uv.lock 的變更都強制 review」+「新包若只有 sdist 無 wheel 需特別注意」機制近似涵蓋。這比 pi 的自動 shrinkwrap 驗證 + 明確 allowlist 稍弱（見 Codex review 回饋）。未來可擴充 check-pinned 或新增 check-build-allowlist.py 做自動偵測 + 清單。
- **未來 PyPI 路徑**（保留）：`uv export --format requirements-txt --frozen --no-dev -o constraints.txt` + `--require-hashes` 安裝，等同 shrinkwrap 層。發布前可加 generate 腳本 + 驗證。

**重要**：本實作已落地 layer 1（exact pin 檢查）與 layer 4（lock 守衛 pre-commit），加上 CI audit 與 pin 強制。Layer 2/3（完整自動 shrinkwrap + install-script allowlist）目前以 committed uv.lock + 強制 review gate 近似實現。文件避免過度宣稱「四層完全等價」。

### 使用與日常

- 新增/更新依賴：編輯 pyproject.toml 為 `pkg==x.y.z` → `uv lock` → `git diff -- uv.lock` 審查 → commit（此時 lock guard 會提醒）。
- 想強制允許 lock 變更（極少情況）：`AGENTX_ALLOW_LOCKFILE_CHANGE=1 git commit ...`
- 安裝/還原：偏好 `uv sync --frozen` 或 hash-pinned 形式。
- pre-commit：`uv run pre-commit install` 之後每次 commit 都會跑 pin 檢查 + lock guard。

### 實作成本：Low（已完成，約 1-2 小時核心 + 文件）

落地檔案（相對 repo 根）：
- `pyproject.toml`（pins）
- `uv.lock`（因 pins 更新，review 後 commit）
- `scripts/check-pinned-deps.py`
- `scripts/check-lockfile-commit.py`
- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`
- 本文件 + AGENTX.md（新增 Dependency and Install Security 段落）

參考來源：pi `scripts/{check-pinned-deps,check-lockfile-commit,generate-coding-agent-shrinkwrap}.mjs`、`.npmrc`、AGENTS.md「Dependency and Install Security」章節。

---

## 2. Provider Registry Pattern（Priority: MEDIUM） — 已實作

agentX 目前有 `OllamaClient` 和 `LlamaCppClient` 兩個 backend，若未來擴充雲端模型支援，這個 pattern 會有用。

### pi 怎麼做（`packages/ai/src/api-registry.ts`，~80 行）

（略，見原文件）

### agentX 落地（2026-06）

- 新增 `src/agentx/provider_registry.py`：定義 `LLMClient` Protocol + 簡單 registry（register_llm_backend / resolve_llm_backend / get_llm_client）。
- 兩個現有 client 在模組底部 self-register（`ollama.py` / `llama_cpp.py` 底部）。
- `cli.py` 的 `build_runtime` 以及兩個 `/model` 切換點改用 `get_llm_client(backend, ...)`。
- 同時 export 到 `agentx/__init__.py`，讓未來 backend 只要 import 自己 + register 即可。
- 變數命名在 build_runtime 內改為較中性的 `llm_client`（回傳 annotation 也更新為 `LLMClient`）。
- 保留 `AGENTX_BACKEND` env 語義，完全相容。

目前只有兩個 backend，所以 registry 很薄，但加第三個（例如 OpenAI / Anthropic）時只要在該模組底部 `register_llm_backend("openai", MyOpenAIClient)` 即可，無需再改 cli.py。

### 實作成本：Low（已完成，概念準備 + 小 refactor）

---

## 3. Hook 契約文件化（Priority: MEDIUM） — 已實作

agentX 的 `HookManager` 功能比 pi 豐富（9 種事件 vs pi 的 2 個 hook），但 pi 的契約寫法更嚴謹，值得學習。

### pi 怎麼做（`packages/agent/src/types.ts`）

（略，見原文件）

### agentX 落地（2026-06）

已在 `src/agentx/hooks.py` 大量補充契約文件（module docstring + HookEvent + HookResult + HookManager.fire）：

- 清楚寫出「MUST NOT raise」（除了 HookVeto 會被轉成 block）、例外吞掉行為。
- 詳細說明 PRE/POST 的回傳語義（block、updated_args、additional_context、system_message）。
- 說明 merge 規則（block OR、最後 wins、context concat）。
- 提及目前 sequential、未來 parallel PRE_TOOL_USE 的可能性（直接引用 pi 語言）。
- 每個 context dataclass 也有基本說明。
- HookManager class 也補了 overview。

實際行為與文件現在一致（fire 已經正確 swallow 非 Veto 例外、正確 merge）。

### 實作成本：Low（已完成，純文件 + 少量強化說明）

---

## 4. 零依賴 SSE Parser（Priority: LOW — 已準備參考實作）

pi 的 `anthropic.ts` 裡有一個手寫的 SSE parser（`iterateSseMessages` / `decodeSseLine` / `consumeLine`），正確處理 `\r\n` / `\r` line endings、comment lines、multi-line data。

agentX 目前走 Ollama HTTP API（JSON streaming），不需要 SSE。但如果未來直接接 Anthropic / OpenAI 的 streaming API（繞過 SDK），這段可以翻成 Python。

### 已實作並整合

- 新增 `src/agentx/sse.py`：零依賴實作，函式命名與行為對齊 pi（`iterate_sse_messages`、`decode_sse_line`、`consume_line`、`parse_sse`）。
- 處理所有提到的 edge case：\r\n/\r/\n line endings、: comment lines、data: 多行累積（用 \n 串接）、標準 event/data/id/retry。
- **真正接進 streaming 路徑**：整合到 `LlamaCppClient._chat_stream`（OpenAI 相容 SSE 格式 `/v1/chat/completions`）。取代原本手動 "data: " 字串處理，更 robust。
- Ollama 維持其原生 NDJSON streaming（非 SSE）。
- 提供 generator 介面，適合 httpx.stream 等。
- 更新文件與 __init__.py export。

### 實作成本：Low（已完成 + 實際整合）

使用時直接 `from agentx.sse import iterate_sse_messages` 即可。

---

## 差異對照（agentX 的優勢）

pi 沒有、但 agentX 已有的功能，供自我確認：

| agentX 有 | pi 沒有 |
|---|---|
| 內建 GREEN/YELLOW/RED 安全分級 | 完全無內建權限（靠容器化） |
| MemoryHall 跨 session 記憶 | 無記憶系統 |
| LearningManager 自我學習 | 無 |
| ErrorClassifier + RecoveryPlaybook | 基本 error mapping |
| JSON repair（補小模型弱點） | 不需要（用大模型） |
| Context compactor（heuristic + LLM） | 有 compaction 但較簡單 |
| `/doctor` 健康檢查 | 無 |
| Task 系統（MT22） | 無 |

這些是 agentX 因為面對本地小模型而發展出的獨特能力，不需要從 pi 借鑑。
