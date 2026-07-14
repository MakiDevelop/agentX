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
| `agentx capabilities --json` | `agentx.capabilities.v1` | `capabilities` |
| `agentx config --json` | `agentx.config.v1` | `config` |
| `agentx inspect --json` | `agentx.inspect.v1` | `inspect` |
| `agentx init --json` | `agentx.init.v1` | `init` |
| `agentx sessions --json` | `agentx.sessions.v1` | `sessions` |
| `agentx artifacts --json` | `agentx.artifacts.v1` | `artifacts` |
| `agentx approvals --json` | `agentx.approvals.v1` | `approvals` |
| `agentx traces --json` | `agentx.traces.v1` | `traces` |
| `agentx diff --json` | `agentx.diff.v1` | `diff` |
| `agentx patch-check --json` | `agentx.patch_check.v1` | `patch_check` |
| `agentx command-plan --json` | `agentx.command_plan.v1` | `command_plan` |
| `agentx review --json` | `agentx.review.v1` | `review` |
| `agentx commit-plan --json` | `agentx.commit_plan.v1` | `commit_plan` |
| `agentx gate --json` | `agentx.gate.v1` | `gate` |
| `agentx next --json` | `agentx.next.v1` | `next` |
| `agentx infra --json` | `agentx.infrastructure_context.v1` | `infra` |
| `agentx tasks --json` | `agentx.tasks.v1` | `tasks` |
| `agentx verify --json` | `agentx.verify.v1` | `verify` |
| `agentx status --json` | `agentx.status.v1` | `status` |
| `agentx doctor --json` | `agentx.doctor.v1` | `doctor` |
| `agentx commands --json` | `agentx.command_catalog.v1` | `commands` |
| `agentx tools --json` | `agentx.tool_catalog.v1` | `tools` |
| `agentx tool-plan --json` | `agentx.tool_plan.v1` | `tool_plan` |
| `agentx workflows --json` | `agentx.workflow_catalog.v1` | `workflows` |
| `agentx version --json` | no `schema` key | `version` |
| `agentx backends --json` | no `schema` key | `backends` |
| `agentx models --json` | backend-specific catalog payload | `models` |

## Capabilities Payload

`agentx capabilities --json` emits `agentx.capabilities.v1`.

This is the top-level runner discovery catalog. It lists non-interactive CLI
capabilities, their stable JSON schemas, JSONL event names, examples, and risk
posture. Use `agentx commands --json` for slash command discovery inside the
interactive shell.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.capabilities.v1`. |
| `query` | string | Filter query, or empty string. |
| `count` | integer | Number of returned capabilities. |
| `capabilities` | array of object | Top-level CLI capability entries. |

Each capability object includes:

| Key | Type |
|-----|------|
| `command` | string |
| `usage` | string |
| `description` | string |
| `examples` | array of string |
| `schemas` | array of string |
| `jsonl_event` | string |
| `risk` | string |

## Inspect Payload

`agentx inspect --json` emits `agentx.inspect.v1`.

This is a read-only aggregate preflight bundle for external runners. It does
not run verification commands or live service probes. Use `agentx verify --json`
when the runner wants to execute checks.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.inspect.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True when the read-only aggregate payload was built successfully. |
| `live_probes` | boolean | Always false; inspect is read-only and local. |
| `recommended_command` | string or null | Top-level copy of `next.recommended_command` for simple runners. |
| `signals` | object | Top-level summary signals copied from `next.signals`, plus inspect-specific counts. |
| `status` | object | Embedded `agentx.status.v1`. |
| `tasks` | object | Embedded `agentx.tasks.v1` filtered to active tasks. |
| `sessions` | object | Embedded `agentx.sessions.v1`. |
| `approvals` | object | Embedded `agentx.approvals.v1` for `latest`. |
| `traces` | object | Embedded `agentx.traces.v1` for `latest`. |
| `diff` | object | Embedded `agentx.diff.v1` for current worktree diff, without patch text. |
| `capabilities` | object | Embedded `agentx.capabilities.v1`. |
| `artifacts` | object | Embedded `agentx.artifacts.v1` catalog for recent headless runner bundles. |
| `next` | object | Embedded `agentx.next.v1` recommendation payload, including command-plan preflights. |
| `verify_commands` | array of object | Detected verification argv lists without executing them. |
| `verify_command_plans` | array of object | Embedded `agentx.command_plan.v1` preflights for each detected verification command. |
| `next_commands` | array of string | Suggested follow-up commands for runners. |

## Diff Payload

`agentx diff [PATH] --json` emits `agentx.diff.v1`.

This is a read-only git diff summary for review and commit runners. By default
it reports unstaged worktree changes. `--staged` reports index changes.
`--patch` is explicit opt-in and includes patch text capped by
`--max-patch-chars`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.diff.v1`. |
| `workspace` | string | Resolved workspace path. |
| `path` | string or null | Workspace-relative path filter, when provided. |
| `staged` | boolean | Whether `--staged` / `git diff --cached` was used. |
| `ok` | boolean | Whether git inspection completed successfully. |
| `is_git_repo` | boolean | Whether the workspace is inside a git work tree. |
| `dirty` | boolean or null | True when matching diff files exist; null outside git. |
| `file_count` | integer | Number of files in `files`. |
| `insertions` | integer | Sum of numeric inserted lines, excluding binary files. |
| `deletions` | integer | Sum of numeric deleted lines, excluding binary files. |
| `binary_count` | integer | Number of binary diff entries. |
| `untracked_count` | integer | Number of untracked files added with `status="??"`; zero for `--staged`. |
| `files` | array of object | Per-file diff summaries. |
| `stat` | string | `git diff --stat --no-color` output. |
| `patch_included` | boolean | True only when `--patch` was requested. |
| `patch` | string or null | Patch text when included, otherwise null. |
| `patch_truncated` | boolean | Whether patch text exceeded `--max-patch-chars`. |
| `detail` | string | Empty string or git / runtime diagnostic text. |

Each file object includes:

| Key | Type | Meaning |
|-----|------|---------|
| `status` | string | `git diff --name-status` status such as `M`, `A`, `D`, `R100`, or `??` for untracked files. |
| `path` | string | Workspace-relative current path. |
| `old_path` | string | Present for rename / copy entries. |
| `added` | integer or null | Inserted lines; null for binary files. |
| `deleted` | integer or null | Deleted lines; null for binary files. |
| `binary` | boolean | Whether the diff entry is binary. |

## Patch Check Payload

`agentx patch-check PATCH --json` emits `agentx.patch_check.v1`.

This is a read-only patch preflight for external runners. It reads a
workspace-relative patch file, runs `git apply --check -`, extracts touched
paths, validates those paths against workspace escape and protected-location
rules, and reports blockers before the interactive `/apply` flow mutates the
worktree. It does not apply the patch, stage files, commit, push, or write a
temporary patch into the workspace.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.patch_check.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `patch_file` | string | Workspace-relative patch file path, or the rejected input when it escaped. |
| `ok` | boolean | True when no blockers are present. |
| `blockers` | array of string | Machine-readable blockers such as `patch_file_not_found`, `patch_file_escapes_workspace`, `git_apply_check_failed`, or `unsafe_patch_paths`. |
| `warnings` | array of string | Non-blocking warnings such as `no_touched_paths_detected`. |
| `apply_check` | object | `git apply --check -` command, ok flag, exit code, stdout, and stderr. |
| `safe_paths_ok` | boolean | True when every detected patch target passed write-path safety checks. |
| `file_count` | integer | Number of detected touched files. |
| `files` | array of object | Per-file path, added/deleted stats when available, binary flag, safe flag, detail, and source list. |
| `next_commands` | array of string | Suggested follow-up commands. Successful checks include `/apply PATCH`. |
| `detail` | string | Combined diagnostic text for blockers. |

## Command Plan Payload

`agentx command-plan COMMAND --json` emits `agentx.command_plan.v1`.

This is a read-only command policy preflight for runners. It parses a shell
command string, checks it against `ALLOWED_COMMANDS`, `BUILD_COMMANDS`, docker
compose policy, and destructive blockers, then returns the matching tool and
approval posture. It never executes the command.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.command_plan.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `command` | string | Original command string after trimming. |
| `argv` | array of string | `shlex.split` result, or empty when syntax is invalid. |
| `ok` | boolean | True when the command matched an allowed policy and has no blockers. |
| `allowed` | boolean | Whether agentX policy allows the command through a known tool. |
| `risk` | string | `GREEN`, `YELLOW`, `RED`, or `UNKNOWN`. |
| `approval_required` | boolean | True for YELLOW build/docker actions. |
| `matched_policy` | string or null | `allowed_command`, `build_command`, `docker_compose`, or null. |
| `tool` | string or null | Tool name that would run the command, such as `run_command`. |
| `tool_args` | object | Tool arguments for the matched tool. |
| `resolved_argv` | array of string or null | Exact argv agentX would use for matched policies. |
| `blockers` | array of string | Machine-readable blockers such as `command_not_allowlisted`, `destructive_git_clean`, or `invalid_command_syntax`. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `next_commands` | array of string | Suggested follow-up commands for humans or runners. |
| `detail` | string | Empty string or a human-readable diagnostic. |

`--fail-on-blocker` still prints the payload first. It exits `1` when
`blockers` is non-empty; otherwise it exits `0`.

## Review Payload

`agentx review --json` emits `agentx.review.v1`.

This is a deterministic review gate for commit/review runners. It does not call
an LLM. It combines `agentx.diff.v1` with `agentx.verify.v1` by default and
returns whether the workspace is ready to enter the commit flow. Use
`--skip-verify` only when the caller wants posture without running checks. Use
`--fail-on-blocker` to print the payload and exit `1` when blockers are present.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.review.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True when no blockers are present. |
| `commit_ready` | boolean | True when there are changes, verification ran, and no blockers are present. |
| `blockers` | array of string | Machine-readable blockers such as `no_changes`, `verify_failed`, or `diff_unavailable`. |
| `warnings` | array of string | Non-blocking warnings such as `verify_skipped` or `has_untracked_files`. |
| `diff` | object | Embedded `agentx.diff.v1`. |
| `verify` | object or null | Embedded `agentx.verify.v1`, or null when `--skip-verify` was used. |
| `next_commands` | array of string | Suggested follow-up commands for humans or runners. |

## Commit Plan Payload

`agentx commit-plan --message TEXT --json` emits `agentx.commit_plan.v1`.

This is a read-only commit planning payload for runners that want to present or
validate a future commit before mutating the git index. It does not stage,
commit, or push. It uses the same file list source as the interactive `/commit`
flow and embeds `agentx.review.v1` for the current review gate.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.commit_plan.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True when no blockers are present. |
| `ready_to_commit` | boolean | True when review passes, a commit message is present, and files exist. |
| `commit_message` | string or null | Proposed commit message. |
| `blockers` | array of string | Machine-readable blockers such as `missing_commit_message`, `verify_failed`, or `no_changes`. |
| `warnings` | array of string | Non-blocking warnings inherited from review. |
| `status` | string | `git status --short --branch` output. |
| `diff_stat` | string | `git diff --stat` output. |
| `files_to_stage` | array of string | Explicit workspace-relative paths that `/commit` would stage one by one. |
| `file_count` | integer | Number of files in `files_to_stage`. |
| `review` | object | Embedded `agentx.review.v1`. |
| `next_commands` | array of string | Suggested follow-up commands for humans or runners. |

## Gate Payload

`agentx gate --json` emits `agentx.gate.v1`.

This is an aggregate deterministic gate for external runners that want one
payload before handing off, committing, or asking a human to approve the next
step. It embeds `agentx.review.v1`, static `agentx.doctor.v1`, and latest
`agentx.approvals.v1` by default. It does not stage, commit, push, deploy, or
call an LLM. Use `--skip-verify`, `--skip-doctor`, or `--skip-approvals` when
the caller intentionally wants a narrower gate. Use `--fail-on-blocker` to print
the payload and exit `1` when blockers are present.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.gate.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True when no blockers are present. |
| `commit_ready` | boolean | True when embedded review is commit-ready and aggregate blockers are empty. |
| `blockers` | array of string | Machine-readable blockers such as `verify_failed`, `doctor_failed`, or `approval_denied`. |
| `warnings` | array of string | Non-blocking warnings such as `verify_skipped`, `doctor_skipped`, `approvals_skipped`, or `approvals_unavailable`. |
| `review` | object | Embedded `agentx.review.v1`. |
| `doctor` | object or null | Embedded static `agentx.doctor.v1`, or null when `--skip-doctor` was used. |
| `approvals` | object or null | Embedded latest `agentx.approvals.v1`, or null when `--skip-approvals` was used. |
| `next_commands` | array of string | Suggested follow-up commands for humans or runners. |

## Next Payload

`agentx next --json` emits `agentx.next.v1`.

This is a deterministic next-step planner for external runners. It reads local
state only: current diff, active tasks, latest artifact bundles, and denied
approval receipts. It does not run verification commands, call an LLM, apply
patches, stage, commit, push, or deploy.

Recommendation priority is intentionally conservative:

1. Denied approval audit.
2. Dirty diff aggregate gate.
3. Latest artifact handoff resume.
4. Active task resume.
5. Idle inspect.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.next.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True when local planning completed. |
| `recommended_command` | string or null | First ranked command from `recommendations`. |
| `recommendations` | array of object | Ranked command recommendations. |
| `signals` | object | Cheap derived booleans/counts used by the planner. |
| `diff` | object | Embedded `agentx.diff.v1`. |
| `tasks` | object | Embedded active `agentx.tasks.v1`. |
| `artifacts` | object | Embedded `agentx.artifacts.v1`. |
| `approvals` | object | Embedded denied-only latest `agentx.approvals.v1`. |

Each recommendation object includes:

| Key | Type |
|-----|------|
| `rank` | integer |
| `kind` | string |
| `command` | string |
| `reason` | string |
| `risk` | string |
| `command_plan` | object, embedded `agentx.command_plan.v1` |

## Infrastructure Context Payload

`agentx infra [all|quick|project|resource|home|vps|resource-bundle] --json`
emits `agentx.infrastructure_context.v1`.

This is a read-only context payload for runtime preflight. It loads Maki's
canonical infrastructure maps from `~/infrastructure/*`, including extracted
home AI facilities and VPS sections. It does not grant permission to SSH,
deploy, restart services, delete data, write memory, or touch production.
Sensitive key/token/secret lines are redacted before the context is returned.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.infrastructure_context.v1`. |
| `map` | string | Requested map key or alias. |
| `ok` | boolean | True when the map context was loaded. |
| `read_only` | boolean | Always true; this payload is evidence only. |
| `content` | string | Bounded markdown context from the selected map source(s). |
| `next_commands` | array of string | Human-facing reminders for runtime state and approval gates. |

## Artifacts Payload

`agentx artifacts --json` emits `agentx.artifacts.v1`.

This is a read-only catalog of saved headless artifact bundles. By default it
scans `.agentx/runs` inside the active workspace. If the argument itself is a
bundle directory, it returns that one bundle. A bundle is any directory with at
least one standard artifact file: `result.json`, `result.jsonl`,
`session.session.jsonl`, or `handoff.md`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.artifacts.v1`. |
| `workspace` | string | Resolved workspace path. |
| `root` | string | Resolved artifact root or bundle directory. |
| `root_relative_path` | string | Workspace-relative root path when possible. |
| `ok` | boolean | Whether discovery completed. Missing roots are still `ok=true` with count 0. |
| `limit` | integer | Maximum number of bundles requested. |
| `count` | integer | Number of returned bundles. |
| `artifacts` | array of object | Bundle summaries sorted by latest artifact mtime descending. |
| `detail` | string | Empty string or a human-readable note. |

Each artifact object includes:

| Key | Type |
|-----|------|
| `name` | string |
| `path` | string |
| `relative_path` | string |
| `updated_at` | string |
| `has_result` | boolean |
| `result_path` | string or null |
| `result_relative_path` | string or null |
| `result_format` | string or null |
| `result_conflict` | boolean |
| `has_session` | boolean |
| `session_path` | string or null |
| `session_relative_path` | string or null |
| `has_handoff` | boolean |
| `handoff_path` | string or null |
| `handoff_relative_path` | string or null |
| `schema_version` | string or null |
| `termination` | string or null |
| `exit_code` | integer or null |
| `needs_handoff` | boolean |
| `resume_command` | string or null |

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

## Traces Payload

`agentx traces [SESSION] --json` emits `agentx.traces.v1`.

This is a read-only transcript observability summary. `SESSION` defaults to
`latest` and can be a transcript stem or file name. Use `agentx sessions --json`
to discover transcript names.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.traces.v1`. |
| `workspace` | string | Resolved workspace path. |
| `session` | string | Requested transcript selector. |
| `ok` | boolean | Whether the transcript was found. |
| `path` | string or null | Transcript path when found. |
| `limit` | integer | Number of recent events requested. |
| `count` | integer | Number of valid JSON object records read. |
| `invalid_line_count` | integer | Lines skipped because they were invalid JSON or not objects. |
| `event_counts` | object | Event name to count. |
| `tool_counts` | object | Tool or command name to count for `tool` events. |
| `approval_count` | integer | Number of approval events. |
| `approval_denied_count` | integer | Number of denied approval events. |
| `tool_failure_count` | integer | Number of `tool` events with `ok=false`. |
| `error_like_count` | integer | Records that look operationally negative: error events, `ok=false`, or `allowed=false`. |
| `first_ts` | string or null | First timestamp seen. |
| `last_ts` | string or null | Last timestamp seen. |
| `recent_events` | array of object | Sanitized newest events, capped by `limit`. |
| `detail` | string | Empty string or a human-readable note. |

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

## Sessions Payload

`agentx sessions --json` emits `agentx.sessions.v1`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.sessions.v1`. |
| `workspace` | string | Resolved workspace path. |
| `count` | integer | Number of returned sessions. |
| `sessions` | array of object | Transcript overviews, newest first. |

Each session object includes:

| Key | Type | Meaning |
|-----|------|---------|
| `name` | string | Transcript stem usable with `/resume NAME`. |
| `started` | string | Session start timestamp or fallback name. |
| `model` | string | Model recorded at session start, or `-`. |
| `namespace` | string | Namespace recorded at session start, or `-`. |
| `turns` | integer | User + assistant turn count. |
| `approval_count` | integer | Number of approval receipts. |
| `approval_denied_count` | integer | Number of denied approval receipts. |
| `approval` | string | Human-readable approval summary. |
| `last` | string | Last compact event summary. |
| `path` | string | Transcript JSONL path. |

## Approvals Payload

`agentx approvals [SESSION] --json` emits `agentx.approvals.v1`.

`SESSION` defaults to `latest` and can be a transcript stem or file name. Use
`--denied` to return only denied approval receipts. Use `--fail-on-denied` to
print the payload first and exit `1` when the returned receipt set contains any
denied approval.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.approvals.v1`. |
| `workspace` | string | Resolved workspace path. |
| `session` | string | Requested transcript selector. |
| `ok` | boolean | Whether the transcript was found. |
| `path` | string or null | Transcript JSONL path when found. |
| `denied_only` | boolean | Whether `--denied` filtering was applied. |
| `limit` | integer | Maximum number of receipts requested. |
| `count` | integer | Number of returned receipts. |
| `denied_count` | integer | Number of returned receipts with `allowed=false`. |
| `receipts` | array of object | Raw approval events from the transcript, newest slice preserving event fields. |
| `detail` | string | Empty on success; diagnostic text when `ok=false`. |

Each receipt preserves the transcript approval event fields, including:

| Key | Type |
|-----|------|
| `ts` | string |
| `event` | string, always `approval` |
| `tool` | string |
| `risk` | string |
| `approval_mode` | string |
| `source` | string |
| `allowed` | boolean |

## Tasks Payload

`agentx tasks [STATUS] --json` emits `agentx.tasks.v1`.

`STATUS` defaults to `all`. Supported filters are `all`, `active`, `pending`,
`in_progress`, `done`, and `blocked`. `active` means `pending`, `in_progress`,
or `blocked`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.tasks.v1`. |
| `workspace` | string | Resolved workspace path. |
| `status_filter` | string | Applied status filter. |
| `count` | integer | Number of returned tasks after filtering. |
| `total_count` | integer | Total number of tasks in `.agentx/tasks.json`. |
| `by_status` | object | Counts for `pending`, `in_progress`, `done`, and `blocked`. |
| `tasks` | array of object | Filtered task objects in storage order. |
| `summary` | string | Human-readable task summary used by prompts and handoff. |

Each task object includes:

| Key | Type |
|-----|------|
| `id` | integer |
| `description` | string |
| `status` | string |
| `notes` | string |

## Verify Payload

`agentx verify --json` emits `agentx.verify.v1`.

The command runs default project verification commands detected from the
workspace. Python projects run `uv run ruff check .` and `uv run pytest -q`.
Node projects run `npm test`. Commands execute sequentially and stop at the
first failure. Use `--fail-on-error` to print the payload first and exit `1`
when `ok=false`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.verify.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `ok` | boolean | True only when every detected verification command passed. |
| `count` | integer | Number of emitted check records. |
| `checks` | array of object | Per-command verification results. |

Each check object includes:

| Key | Type | Meaning |
|-----|------|---------|
| `command` | string | Shell-escaped display command. |
| `argv` | array of string | Executed argv list; no shell expansion. |
| `ok` | boolean | Whether the command passed. |
| `exit_code` | integer or null | Process exit code; `124` for timeout. |
| `stdout` | string | Captured stdout, truncated. |
| `stderr` | string | Captured stderr, truncated. |
| `output` | string | Preferred compact output for humans and logs. |

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
| `by_risk` | object | Counts for GREEN, YELLOW, and RED tools in the returned list. |
| `tools` | array of object | Tool metadata. |

Each tool object includes:

| Key | Type |
|-----|------|
| `name` | string |
| `description` | string |
| `risk` | string |
| `signature` | string |
| `aliases` | array of string |

## Tool Plan Payload

`agentx tool-plan TOOL --args-json JSON --json` emits `agentx.tool_plan.v1`.

This is a read-only tool-call preflight for runners. It resolves tool aliases,
parses args JSON, reports risk and approval posture, and performs basic known
arg checks for write paths, git staging paths, run command allowlists, and
docker compose availability. It never executes the tool.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.tool_plan.v1`. |
| `workspace` | string | Resolved workspace path. |
| `generated_at` | string | Local ISO timestamp. |
| `requested_tool` | string | Tool name or alias requested by the caller. |
| `canonical_tool` | string or null | Primary registered tool name after alias resolution. |
| `exists` | boolean | Whether the tool exists. |
| `enabled` | boolean | Whether the tool is enabled in this environment. |
| `ok` | boolean | True when the tool exists, is enabled, is not RED, args parse, and known arg checks pass. |
| `risk` | string | Tool risk: `GREEN`, `YELLOW`, `RED`, or `UNKNOWN`. |
| `approval_required` | boolean | True for YELLOW tools. |
| `args` | object | Parsed tool arguments. |
| `signature` | string | Tool signature metadata from the catalog. |
| `description` | string | Tool description metadata from the catalog. |
| `aliases` | array of string | Registered aliases for the canonical tool. |
| `blockers` | array of string | Machine-readable blockers such as `unknown_tool`, `invalid_args_json`, `unsafe_write_path`, or `run_command_requires_green_allowlist`. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `next_commands` | array of string | Suggested follow-up actions. |
| `detail` | string | Empty string or a human-readable diagnostic. |

`--fail-on-blocker` still prints the payload first. It exits `1` when
`blockers` is non-empty; otherwise it exits `0`.

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
- `tests/test_sessions_cli.py`
- `tests/test_status_cli.py`
- `tests/test_doctor_cli.py`
- `tests/test_command_catalog_cli.py`
- `tests/test_tool_catalog_cli.py`
- `tests/test_workflows_cli.py`

Run:

```bash
uv run pytest -q tests/test_config_cli.py tests/test_init_cli.py tests/test_sessions_cli.py tests/test_status_cli.py tests/test_doctor_cli.py tests/test_command_catalog_cli.py tests/test_tool_catalog_cli.py tests/test_workflows_cli.py
```
