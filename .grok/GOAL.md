# GOAL — agentX harness 極緻改造

- **Status:** done
- **Owner agent:** grok
- **Line / project:** ② agentX
- **Started:** 2026-08-14
- **Updated:** 2026-08-14

## Intent（一句話）

把 agentX 的 operating environment 改成能載本地大模型、行為接近 Claude Code / Codex CLI / Grok Build CLI，而不是再用文字補 architecture bug。

## Definition of Done（可勾選、可驗證）

- [x] 模型可用 Ollama native tool calling；JSON-in-text 只當 fallback
- [x] 預設就是 agent 模式；max_steps 足夠跑完讀→改→驗證
- [x] gemma4:31b 這類大模型不再被套「弱模型微步儀式」
- [x] context 不再每輪倒完整 AGENTX.md 治理文
- [x] `/mode` 切換保留上一模式對話；寫檔任務未改檔不能 final
- [x] VERIFY: `uv run pytest -q` → 1080 passed, 1 skipped, 1 xfailed

## Out of scope / 紅線

- 不重寫 cli.py 剩餘 1 萬行拆分
- 不改 production / 不 push（除非 Chair 指示）
- 不刪 .agentx 記憶層
- 不把 AGENTX.md 開發憲法重寫成 runtime prompt

## Verify suite（完成前必跑）

```bash
cd ~/GitHub/agentX
uv run ruff check src/agentx/chat_turn.py src/agentx/tool_schemas.py src/agentx/model_size.py src/agentx/ollama.py src/agentx/loop.py src/agentx/runtime_prompt.py src/agentx/bootstrap.py src/agentx/config.py src/agentx/persona.py src/agentx/cli_runtime_handlers.py
uv run pytest -q tests/test_tool_schemas.py tests/test_ollama_native.py tests/test_harness_upgrade.py tests/test_agent_session.py tests/test_runtime_prompt.py tests/test_bootstrap.py tests/test_prompt_tool_drift.py tests/test_persona.py tests/test_cli_runtime_handlers.py
```

## Progress log

| 時間 | 完成 | 證據 |
|------|------|------|
| | | |

## Attempts（撞牆計數）

| 問題 | 次數 | 最後證據 | 狀態 |
|------|------|----------|------|
| | 0 | | open |

## Blockers（等 Chair / 外部）

- 無

## Notes

- 真實 session 20260812：chat 預設 + 切 mode 失憶 + 叫使用者去 zsh 打 /fetch
- 8/12 hardening 已修 prompt 漂移 / token 低估 / 工具輸出無上限；沒修「模型根本拿不到 native tools」
