# agentX

Local agent shell for Ollama models, designed to give a local Gemma-class model a
Claude/Codex-like runtime: tools, Memory Hall, safety gates, and execution traces.

## MVP scope

This first version is intentionally read-heavy:

- Ollama chat adapter
- Memory Hall search/write adapter
- JSON tool-call loop
- Read-only filesystem and git tools
- Safety classifier for future write/execute tools
- CLI entrypoint: `agentx ask`

## Setup

```bash
uv sync --extra dev
ollama serve
ollama pull gemma3:latest
```

Optional environment:

```bash
export AGENTX_MODEL=gemma3:latest
export AGENTX_MEMORY_HALL_URL=http://100.122.171.74:9100
export AGENTX_MEMORY_HALL_TOKEN=...
```

## Usage

```bash
uv run agentx chat "只回一句話：你是什麼？"
uv run agentx ask "這個 repo 是做什麼的？"
uv run agentx ask "查 Memory Hall，整理 agentX 相關記憶" --namespace project:agentX
uv run agentx ask "找出這個 repo 的測試怎麼跑"
```

Use `chat` when you only want to test model speed or have a plain conversation.
Use `ask` when you want the agent loop and tools.

For slow local models:

```bash
AGENTX_MODEL=gemma4:e2b AGENTX_OLLAMA_TIMEOUT=30 uv run agentx chat "只回一句話"
AGENTX_MODEL=gemma4:e2b uv run agentx ask "列出 repo 檔案" --max-steps 2
```

The model must return one of these JSON envelopes:

```json
{"type":"tool_call","tool":"search_text","args":{"pattern":"pytest"}}
{"type":"final","content":"答案..."}
```

If the model emits plain text or invalid JSON, agentX treats it as a final answer
instead of executing anything.

## Current tools

- `list_files`
- `read_file`
- `search_text`
- `git_status`
- `git_diff`
- `memory_search`
- `memory_write`

## Safety model

- GREEN: read-only operations, automatic
- YELLOW: reversible mutations, require approval in later versions
- RED: destructive or sensitive operations, blocked unless explicitly approved by Maki

Patch/edit/command execution tools are deliberately left out of this MVP.
