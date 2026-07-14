# CLI JSON Contracts

This document defines the stable machine-readable contracts for local,
non-interactive inspection commands such as `agentx config --json`,
`agentx status --json`, `agentx doctor --json`, and catalog commands.

Headless agent run results are documented separately in
`docs/HEADLESS_PAYLOAD_CONTRACT.md`.

## Compatibility Rules

- Existing top-level keys are append-only. Do not remove or rename them without
  an explicit migration note and test update.
- New keys may be added at any object level.
- Consumers should ignore unknown keys.
- `--output-format jsonl` emits one JSON object per line:

```json
{"event":"status","data":{"schema":"agentx.status.v1"}}
```

Consumers should branch on `event` and read the payload from `data`.

## Event Names

| Command | JSON schema | JSONL event |
|---------|-------------|-------------|
| `agentx config --json` | `agentx.config.v1` | `config` |
| `agentx init --json` | `agentx.init.v1` | `init` |
| `agentx status --json` | `agentx.status.v1` | `status` |
| `agentx doctor --json` | `agentx.doctor.v1` | `doctor` |
| `agentx commands --json` | `agentx.command_catalog.v1` | `commands` |
| `agentx tools --json` | `agentx.tool_catalog.v1` | `tools` |
| `agentx workflows --json` | `agentx.workflow_catalog.v1` | `workflows` |
| `agentx version --json` | no `schema` key | `version` |
| `agentx backends --json` | no `schema` key | `backends` |
| `agentx models --json` | backend-specific catalog payload | `models` |

## Config Payload

`agentx config --json` emits `agentx.config.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.config.v1`. |
| `workspace` | string | Resolved workspace path. |
| `model` | string | Resolved model name. |
| `ollama_url` | string | Resolved Ollama-compatible base URL. |
| `ollama_timeout` | number | Request timeout seconds. |
| `memory_backend` | string | Configured memory backend. |
| `memory_amh_store` | string or null | AMH store type when configured. |
| `memory_amh_path` | string or null | AMH store path when configured. |
| `memory_hall_url` | string | Legacy memhall URL. |
| `memory_hall_token` | string | Token status only: `set` or `missing`; never the secret value. |
| `max_steps` | integer | Agent loop max steps. |
| `context_limit_tokens` | integer | Context limit setting. |
| `auto_handoff` | boolean | Whether auto handoff is enabled. |
| `persona` | string | Resolved persona. |
| `namespace` | string | Resolved namespace. |
| `mode` | string | Resolved mode; `ask` is normalized to `agent`. |
| `approval` | string | Canonical approval mode. |
| `learning_enabled` | boolean | Whether self-learning proposals are enabled. |
| `project_config` | object | Raw project config values before runtime defaults. |

## Init Payload

`agentx init --json` emits `agentx.init.v1`.

By default this command is read-only. It scans the workspace and prints the
project profile. `--write-memory` is the explicit opt-in side effect that writes
the profile to Memory Hall.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.init.v1`. |
| `workspace` | string | Resolved workspace path. |
| `namespace` | string | Target namespace. |
| `write_memory` | boolean | Whether this invocation attempted a Memory Hall write. |
| `memory_result` | object or null | Write result when `--write-memory` is used. |
| `profile` | object | Embedded `agentx.project_profile.v1` payload. |

`profile` required keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.project_profile.v1`. |
| `namespace` | string | Namespace used for the profile. |
| `workspace` | string | Resolved workspace path. |
| `detected` | array of string | Detected project traits. |
| `test_commands` | array of string | Suggested verification commands. |
| `repo_context` | string | Bootstrap context excerpt for human/agent review. |

## Status Payload

`agentx status --json` emits `agentx.status.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.status.v1`. |
| `version` | object | AgentX and Python versions. |
| `workspace` | string | Resolved workspace path. |
| `runtime` | object | Compact runtime posture. |
| `git` | object | Local `git status --short --branch` summary. |
| `tasks` | object | `.agentx/tasks.json` counts and active tasks. |
| `config` | object | Embedded `agentx.config.v1` payload. |

`runtime` required keys:

| Key | Type |
|-----|------|
| `model` | string |
| `namespace` | string |
| `mode` | string |
| `approval` | string |
| `persona` | string |
| `memory_backend` | string |
| `auto_handoff` | boolean |

`git` required keys:

| Key | Type | Meaning |
|-----|------|---------|
| `ok` | boolean | Whether git status command succeeded. |
| `branch` | string or null | Current branch or detached head label. |
| `upstream` | string or null | Upstream branch when present. |
| `ahead` | integer | Commits ahead of upstream. |
| `behind` | integer | Commits behind upstream. |
| `detached` | boolean | Whether HEAD is detached. |
| `initial` | boolean | Whether repository has no commits yet. |
| `dirty` | boolean or null | Worktree/index dirty state, null when git failed. |
| `changes_count` | integer or null | Number of porcelain status lines. |
| `changes` | array of string | First 50 porcelain status lines. |
| `detail` | string | Empty on success; diagnostic output on failure. |

`tasks` required keys:

| Key | Type |
|-----|------|
| `count` | integer |
| `by_status` | object with `pending`, `in_progress`, `done`, `blocked` |
| `active` | array of compact task objects |

## Doctor Payload

`agentx doctor --json` emits `agentx.doctor.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.doctor.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `live_probes` | boolean | False when `--static` skips Ollama and memory probes. |
| `ok` | boolean | True only when every check is ok. |
| `checks` | array of object | Normalized health checks. |

Each check has:

| Key | Type |
|-----|------|
| `name` | string |
| `ok` | boolean |
| `detail` | string |

`agentx doctor --fail-on-error` still prints the payload first. It exits `1`
when `ok=false`; otherwise it exits `0`. Without `--fail-on-error`, doctor exits
`0` after a successful payload emission even when a check failed.

## Command Catalog Payload

`agentx commands --json` emits `agentx.command_catalog.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.command_catalog.v1`. |
| `query` | string or null | Filter query. |
| `count` | integer | Number of returned commands. |
| `commands` | array of object | Command metadata. |

Each command object includes:

| Key | Type |
|-----|------|
| `command` | string |
| `usage` | string |
| `description` | string |
| `examples` | array of string |
| `related` | array of string |
| `risk` | string |

## Tool Catalog Payload

`agentx tools --json` emits `agentx.tool_catalog.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.tool_catalog.v1`. |
| `query` | string or null | Filter query. |
| `count` | integer | Number of returned tools. |
| `tools` | array of object | Tool metadata. |

Each tool object includes:

| Key | Type |
|-----|------|
| `name` | string |
| `description` | string |
| `risk` | string |
| `keywords` | array of string |

## Workflow Catalog Payload

`agentx workflows --json` emits `agentx.workflow_catalog.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.workflow_catalog.v1`. |
| `query` | string or null | Workflow name or alias filter. |
| `count` | integer | Number of returned workflows. |
| `workflows` | array of object | Workflow recipes. |

Each workflow object includes:

| Key | Type |
|-----|------|
| `goal` | string |
| `path` | string |
| `aliases` | array of string |

## Stability Tests

Contract coverage lives in:

- `tests/test_config_cli.py`
- `tests/test_init_cli.py`
- `tests/test_status_cli.py`
- `tests/test_doctor_cli.py`
- `tests/test_command_catalog_cli.py`
- `tests/test_tool_catalog_cli.py`
- `tests/test_workflows_cli.py`

Run:

```bash
uv run pytest -q tests/test_config_cli.py tests/test_init_cli.py tests/test_status_cli.py tests/test_doctor_cli.py tests/test_command_catalog_cli.py tests/test_tool_catalog_cli.py tests/test_workflows_cli.py
```
