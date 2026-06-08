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

## 2. Provider Registry Pattern（Priority: MEDIUM）

agentX 目前有 `OllamaClient` 和 `LlamaCppClient` 兩個 backend，若未來擴充雲端模型支援，這個 pattern 會有用。

### pi 怎麼做（`packages/ai/src/api-registry.ts`，~80 行）

```typescript
// 簡化版核心概念
const registry = new Map<ApiType, ApiProvider>();

function registerApiProvider(api: ApiType, provider: ApiProvider, sourceId?: string) {
    // sourceId 追蹤是誰註冊的（用於 extension unregister）
    registry.set(api, { ...provider, sourceId });
}

function resolveApiProvider(api: ApiType): ApiProvider {
    const provider = registry.get(api);
    if (!provider) throw new Error(`No provider registered for API: ${api}`);
    return provider;
}

// 每個 provider 註冊時附帶 runtime type guard
function wrapStream(api: ApiType, streamFn: StreamFunction): StreamFunction {
    return (model, context, options) => {
        if (model.api !== api) throw new Error(`Model api mismatch: expected ${api}, got ${model.api}`);
        return streamFn(model, context, options);
    };
}
```

### agentX 等價做法

```python
# src/agentx/provider_registry.py

from typing import Protocol, Dict

class LLMProvider(Protocol):
    async def stream(self, messages: list, model: str, tools: list | None = None) -> AsyncIterator: ...
    async def complete(self, messages: list, model: str) -> dict: ...

_registry: Dict[str, LLMProvider] = {}

def register_provider(api_type: str, provider: LLMProvider, source_id: str | None = None):
    _registry[api_type] = provider

def resolve_provider(api_type: str) -> LLMProvider:
    if api_type not in _registry:
        raise ValueError(f"No provider for: {api_type}")
    return _registry[api_type]

# 用法：
# register_provider("ollama", OllamaClient(...))
# register_provider("llama_cpp", LlamaCppClient(...))
# register_provider("openai", OpenAIClient(...))  # 未來
```

目前 agentX 的 `OllamaClient` / `LlamaCppClient` 是在 `config.py` 直接選擇的。抽出 registry 只有在加第三個 backend 時才值得做。

### 實作成本：Low（概念級，需要時再做）

---

## 3. Hook 契約文件化（Priority: MEDIUM）

agentX 的 `HookManager` 功能比 pi 豐富（8 種事件 vs pi 的 2 個 hook），但 pi 的契約寫法更嚴謹，值得學習。

### pi 怎麼做（`packages/agent/src/types.ts`）

每個 hook callback 的 JSDoc 明確寫出：

1. **不可 throw** — "Callbacks must not throw or reject; uncaught errors will terminate the agent loop"
2. **回傳語義** — "Return `{ block: true, reason: '...' }` to prevent execution; return `undefined` to allow"
3. **並行 vs 序列** — "When `toolExecution` is `'parallel'`, multiple `beforeToolCall` may fire concurrently"
4. **合併語義** — "AfterToolCallResult fields are merged: `content` replaces, `details` replaces, `terminate` replaces, `isError` replaces"

### agentX 應該補的

在 `hooks.py` 的 `HookEvent` 和 `HookManager.fire()` 上補 docstring：

```python
class HookEvent(Enum):
    """Agent lifecycle events.

    Hook callbacks for all events:
    - MUST NOT raise exceptions (uncaught errors are logged and swallowed)
    - MUST complete within 5 seconds (long operations should be fire-and-forget)
    - MAY be called concurrently for PRE_TOOL_USE when parallel tool execution is enabled
    """
    SESSION_START = "session_start"    # Fired once at session creation. Args: session_id, model, namespace
    PRE_TOOL_USE = "pre_tool_use"      # Fired before each tool execution. Args: tool_name, args, risk_level
    POST_TOOL_USE = "post_tool_use"    # Fired after each tool execution. Args: tool_name, result, is_error
    # ...
```

### 實作成本：Low（純文件，1 小時）

---

## 4. 零依賴 SSE Parser（Priority: LOW — 目前不需要）

pi 的 `anthropic.ts` 裡有一個手寫的 SSE parser（`iterateSseMessages` / `decodeSseLine` / `consumeLine`），正確處理 `\r\n` / `\r` line endings、comment lines、multi-line data。

agentX 目前走 Ollama HTTP API（JSON streaming），不需要 SSE。但如果未來直接接 Anthropic / OpenAI 的 streaming API（繞過 SDK），這段可以翻成 Python。

留作參考，不主動實作。

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
