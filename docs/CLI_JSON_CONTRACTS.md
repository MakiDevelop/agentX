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
| `agentx instructions --json` | `agentx.local_instructions.v1` | `instructions` |
| `agentx config --json` | `agentx.config.v1` | `config` |
| `agentx memory-status --json` | `agentx.memory_status.v1` | `memory_status` |
| `agentx memory-read --json` | `agentx.memory_read.v1` | `memory_read` |
| `agentx memory-write --json` | `agentx.memory_write.v1` | `memory_write` |
| `agentx inspect --json` | `agentx.inspect.v1` | `inspect` |
| `agentx init --json` | `agentx.init.v1` | `init` |
| `agentx sessions --json` | `agentx.sessions.v1` | `sessions` |
| `agentx artifacts --json` | `agentx.artifacts.v1` | `artifacts` |
| `agentx handoff-inspect --json` | headless result inspection payload | `handoff_inspect` |
| `agentx handoff-resume --json` | resume command field payload | `handoff_resume` |
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
| `agentx ace-init --json` | `agentx.ace_session.v1` | `ace_init` |
| `agentx ace-append --json` | `agentx.ace_append.v1` | `ace_append` |
| `agentx ace-briefing --json` | `agentx.ace_briefing.v1` | `ace_briefing` |
| `agentx ace-answer --json` | `agentx.ace_answer.v1` | `ace_answer` |
| `agentx ace-status --json` | `agentx.ace_status.v1` | `ace_status` |
| `agentx tasks --json` | `agentx.tasks.v1` | `tasks` |
| `agentx task-update --json` | `agentx.task_update.v1` | `task_update` |
| `agentx verify --json` | `agentx.verify.v1` | `verify` |
| `agentx status --json` | `agentx.status.v1` | `status` |
| `agentx doctor --json` | `agentx.doctor.v1` | `doctor` |
| `agentx commands --json` | `agentx.command_catalog.v1` | `commands` |
| `agentx tools --json` | `agentx.tool_catalog.v1` | `tools` |
| `agentx tool-plan --json` | `agentx.tool_plan.v1` | `tool_plan` |
| `agentx workflows --json` | `agentx.workflow_catalog.v1` | `workflows` |
| `agentx workflow-plan --json` | `agentx.workflow_plan.v1` | `workflow_plan` |
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
| `recommended_entrypoints` | array of object | Suggested runner entrypoints for discovery, workspace preflight, infrastructure preflight, next-step planning, gates, and verification. |
| `by_schema` | object | Map from schema name to the command, usage, and JSONL event that emits it, scoped to the returned capabilities. |
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

## Local Instructions Payload

`agentx instructions --json` emits `agentx.local_instructions.v1`.

This command is read-only. It reports repo-local instruction files in the same
priority order used by bootstrap context: `AGENTX.md`, `AGENTS.md`, then
`CLAUDE.md`. These files provide project guidance and cannot override agentX
safety policy.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.local_instructions.v1`. |
| `ok` | boolean | True when inspection completed. Missing instruction files are a warning, not a blocker. |
| `workspace` | string | Resolved workspace path. |
| `priority` | array of string | Instruction file priority order. |
| `selected_file` | string or null | First existing instruction file by priority. |
| `found_count` | integer | Number of existing instruction files. |
| `files` | array of object | One entry per known instruction file, including `name`, `path`, `purpose`, `exists`, `priority`, `size`, `included_chars`, `truncated`, and `content_excerpt`. |
| `context` | string | Merged local instruction context capped by `--max-chars`. |
| `context_truncated` | boolean | Whether merged context was capped. |
| `blockers` | array of string | Machine-readable blockers. Currently empty for successful read-only inspection. |
| `warnings` | array of string | Non-blocking diagnostics such as `no_local_instruction_files_found`. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | Suggested follow-up kind. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

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
| `recommended_kind` | string or null | Top-level copy of `next.recommended_kind` for simple runners. |
| `recommended_risk` | string or null | Top-level copy of `next.recommended_risk` for simple runners. |
| `signals` | object | Top-level summary signals copied from `next.signals`, plus inspect-specific counts/posture such as `verify_command_count`, `verify_command_plan_count`, `local_instruction_found_count`, `local_instruction_selected_file`, `memory_backend`, `memory_ok`, and `amh_available`. |
| `status` | object | Embedded `agentx.status.v1`. |
| `tasks` | object | Embedded `agentx.tasks.v1` filtered to active tasks. |
| `sessions` | object | Embedded `agentx.sessions.v1`. |
| `approvals` | object | Embedded `agentx.approvals.v1` for `latest`. |
| `traces` | object | Embedded `agentx.traces.v1` for `latest`. |
| `diff` | object | Embedded `agentx.diff.v1` for current worktree diff, without patch text. |
| `capabilities` | object | Embedded `agentx.capabilities.v1`. |
| `instructions` | object | Embedded `agentx.local_instructions.v1` repo-local instruction inspection payload. |
| `memory_status` | object | Embedded `agentx.memory_status.v1` read-only memory backend posture payload, with `live_probe=false`. |
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
| `recommended_command` | string | First suggested follow-up command for simple runners. Successful checks recommend `/apply PATCH`; blockers recommend fixing patch blockers and rerunning patch-check. |
| `recommended_kind` | string | `apply_patch` when checks pass, otherwise `fix_patch_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. Successful checks include `/apply PATCH`. |
| `detail` | string | Combined diagnostic text for blockers. |

## Command Plan Payload

`agentx command-plan COMMAND --json` emits `agentx.command_plan.v1`.

This is a read-only command policy preflight for runners. It parses a shell
command string, checks it against `ALLOWED_COMMANDS`, `BUILD_COMMANDS`, docker
compose policy, top-level `agentx` CLI capabilities, headless `agentx -p`
posture, and destructive blockers, then returns the matching tool and approval
posture. It never executes the command.

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
| `approval_required` | boolean | True for YELLOW build/docker/headless agent actions. |
| `matched_policy` | string or null | `allowed_command`, `build_command`, `docker_compose`, `agentx_headless`, `agentx_cli_capability`, or null. |
| `tool` | string or null | Tool name that would run the command, such as `run_command`. |
| `tool_args` | object | Tool arguments for the matched tool. |
| `resolved_argv` | array of string or null | Exact argv agentX would use for matched policies. |
| `blockers` | array of string | Machine-readable blockers such as `command_not_allowlisted`, `destructive_git_clean`, or `invalid_command_syntax`. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `recommended_command` | string or null | First suggested follow-up command for simple runners, copied from `next_commands[0]` when present. |
| `recommended_kind` | string or null | Machine-readable kind such as `run_command`, `run_build_command`, `agentx_headless`, `agentx_cli`, `fix_blockers`, or `do_not_execute`. |
| `recommended_risk` | string or null | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands for humans or runners. |
| `detail` | string | Empty string or a human-readable diagnostic. |

`--fail-on-blocker` still prints the payload first. It exits `1` when
`blockers` is non-empty; otherwise it exits `0`.

For `matched_policy="agentx_cli_capability"`, `tool_args` includes
`capability_command`, `usage`, `schemas`, `jsonl_event`, and `description` from
`agentx.capabilities.v1`. This lets runners inspect the expected output schema
and JSONL event without a second capabilities lookup.

For `matched_policy="agentx_headless"`, `tool_args` includes runner posture
metadata such as `agent_mode`, `prompt_source`, `workspace_override`,
`prompt_source_count`, `prompt_file`, `artifact_dir`, `result_output`, `session_output`,
`handoff_briefing_output`, `save_session`, `resume_session`, `quiet`, and
`output_format`. It also exposes execution posture fields for wrappers:
`dry_run`, `plan_mode`, `plan_then_execute`, `orchestrate`, `no_memory`,
`approval_override`, `backend_override`, `base_url_override`, `model_override`,
`request_timeout`, `run_timeout`, `max_steps`, and `result_output_format`.
Both `--option value` and `--option=value` forms are recognized for these
metadata fields.
Headless blockers include `headless_prompt_sources_conflict`,
`headless_prompt_file_escapes_workspace`,
`headless_artifact_dir_conflicts_with_output_options`,
`headless_output_paths_conflict`, `headless_artifact_dir_requires_agent`,
`headless_handoff_briefing_output_requires_agent`, and
`headless_session_output_conflicts_with_resume_session`. Output path blockers
also include `headless_output_path_escapes_workspace`.

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
| `recommended_command` | string | First suggested follow-up command or instruction for simple runners. |
| `recommended_kind` | string | Machine-readable kind for `recommended_command`, such as `commit`, `verify`, or `fix_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
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
| `recommended_command` | string | First suggested follow-up command or instruction for simple runners. |
| `recommended_kind` | string | Machine-readable kind for `recommended_command`, such as `commit`, `review`, or `fix_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
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
| `recommended_command` | string | First suggested follow-up command or instruction for simple runners. |
| `recommended_kind` | string | Machine-readable kind for `recommended_command`, such as `commit_plan`, `gate`, or `fix_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
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
| `recommended_kind` | string or null | First ranked recommendation kind, copied for simple runners. |
| `recommended_risk` | string or null | First ranked recommendation risk, copied for simple runners. |
| `recommendations` | array of object | Ranked command recommendations. |
| `signals` | object | Cheap derived booleans/counts used by the planner. |
| `diff` | object | Embedded `agentx.diff.v1`. |
| `tasks` | object | Embedded active `agentx.tasks.v1`. |
| `artifacts` | object | Embedded `agentx.artifacts.v1`. |
| `approvals` | object | Embedded denied-only latest `agentx.approvals.v1`. |

`signals` includes `dirty`, `diff_ok`, `active_task_count`,
`active_task_ids`, `primary_active_task`, `artifact_count`,
`latest_artifact_needs_handoff`, `denied_approval_count`, and
`approvals_available`. `primary_active_task` is the first task from the embedded
active `tasks` payload, or null when no active tasks exist.

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
| `resolved_map` | string | Canonical map key after alias resolution, such as `home`, `vps`, or `resource-bundle`. |
| `alias_applied` | boolean | True when `map` was a natural-language alias. |
| `ok` | boolean | True when the map context was loaded. |
| `read_only` | boolean | Always true; this payload is evidence only. |
| `source_status` | string | `complete` when all selected source files exist, otherwise `missing`. |
| `selected_maps` | array of string | Canonical selected map slices, such as `["resource", "home", "vps"]` for `resource-bundle`. |
| `sources` | array of object | Selected source metadata with `key`, `title`, `path`, `exists`, and `section_headings`. |
| `limits` | object | Applied `per_file_chars` and `max_chars` caps. |
| `content` | string | Bounded markdown context from the selected map source(s). |
| `next_commands` | array of string | Human-facing reminders for runtime state and approval gates. |

## ACE Session Payload

`agentx ace-init SESSION --goal GOAL --json` emits `agentx.ace_session.v1`.

This command previews or creates an Agent Context Exchange session directory
for file-based multi-agent coordination. By default it is a dry-run and writes
nothing. Add `--write` to create `<root>/<SESSION>/_manifest.md`. The default
root is `~/Documents/agent-council`; tests and wrappers can override it with
`--root`.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.ace_session.v1`. |
| `ok` | boolean | True when the manifest preview or write succeeded. |
| `write` | boolean | True when `--write` was requested. |
| `session_id` | string | Validated session id / directory name. |
| `root` | string | Resolved ACE root directory. |
| `session_dir` | string or null | Resolved session directory. |
| `manifest_path` | string or null | Resolved `_manifest.md` path. |
| `manifest_exists` | boolean | Whether `_manifest.md` exists after the operation. |
| `blockers` | array of string | Machine-readable blockers such as `manifest_already_exists` or invalid session id errors. |
| `warnings` | array of string | Non-blocking diagnostics such as `dry_run_no_files_written`. |
| `manifest` | string | Rendered `_manifest.md` content. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `ace_init_write`, `next`, or `fix_ace_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

The generated manifest includes the ACE-required sections `GOAL`,
`ROUTING DECISIONS`, `SUB-TASKS`, `CUMULATIVE FINDINGS`, `DECISIONS TAKEN`,
and `OPEN QUESTIONS`.

## ACE Append Payload

`agentx ace-append SESSION SECTION TEXT --json` emits `agentx.ace_append.v1`.

This command appends one timestamped bullet to an existing ACE `_manifest.md`.
Supported `SECTION` values are `routing`, `sub-task` / `subtask`, `finding`,
`decision`, and `question`. It does not create a session; use `agentx ace-init
SESSION --goal GOAL --write` first.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.ace_append.v1`. |
| `ok` | boolean | True when the manifest was updated. |
| `session_id` | string | Validated session id / directory name. |
| `root` | string | Resolved ACE root directory. |
| `session_dir` | string or null | Resolved session directory. |
| `manifest_path` | string or null | Resolved `_manifest.md` path. |
| `section` | string | Normalized requested section. |
| `heading` | string | Manifest heading that received the entry. |
| `entry` | string | Timestamped bullet appended to the manifest. |
| `manifest_exists` | boolean | Whether `_manifest.md` exists. |
| `blockers` | array of string | Machine-readable blockers such as `manifest_not_found`, `unknown_section`, or `manifest_section_missing`. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `manifest` | string | Updated manifest content when ok, otherwise best-effort current content. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `next` when ok, otherwise `fix_ace_append_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

## ACE Briefing Payload

`agentx ace-briefing SESSION --agent AGENT --json` emits
`agentx.ace_briefing.v1`.

This command creates a scoped briefing from an existing ACE `_manifest.md` for a
single target agent. By default it is a dry-run and writes nothing. Add
`--write` to create `briefing-AGENT.md` or pass `--output FILENAME` to choose a
different filename inside the ACE session directory.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.ace_briefing.v1`. |
| `ok` | boolean | True when the briefing preview or write succeeded. |
| `write` | boolean | True when `--write` was requested. |
| `session_id` | string | Validated session id / directory name. |
| `agent` | string | Validated target agent slug. |
| `role` | string | Role included in the briefing. |
| `root` | string | Resolved ACE root directory. |
| `session_dir` | string or null | Resolved session directory. |
| `manifest_path` | string or null | Resolved `_manifest.md` path. |
| `briefing_path` | string or null | Resolved briefing output path. |
| `briefing_exists` | boolean | Whether the briefing file exists after the operation. |
| `blockers` | array of string | Machine-readable blockers such as `manifest_not_found`, `briefing_already_exists`, or unsafe output errors. |
| `warnings` | array of string | Non-blocking diagnostics such as `dry_run_no_files_written`. |
| `briefing` | string | Rendered briefing markdown. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `ace_briefing_write`, `next`, or `fix_ace_briefing_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

## ACE Answer Payload

`agentx ace-answer SESSION --agent AGENT --answer TEXT --json` emits
`agentx.ace_answer.v1`.

This command records one external agent answer as a new markdown file in the ACE
session directory and appends a summary pointer back to `_manifest.md`. It is
append-only by default: existing answer filenames are rejected.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.ace_answer.v1`. |
| `ok` | boolean | True when the answer file and manifest update succeeded. |
| `session_id` | string | Validated session id / directory name. |
| `agent` | string | Validated answer author slug. |
| `root` | string | Resolved ACE root directory. |
| `session_dir` | string or null | Resolved session directory. |
| `manifest_path` | string or null | Resolved `_manifest.md` path. |
| `answer_path` | string or null | Resolved answer file path. |
| `answer_exists` | boolean | Whether the answer file exists after the operation. |
| `section` | string | Normalized manifest section that received the summary. |
| `heading` | string | Manifest heading that received the summary. |
| `entry` | string | Timestamped summary bullet appended to the manifest. |
| `blockers` | array of string | Machine-readable blockers such as `answer_required`, `answer_already_exists`, `manifest_not_found`, or unsafe output errors. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `answer_document` | string | Rendered answer markdown. |
| `manifest` | string | Updated manifest content when ok. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `next` when ok, otherwise `fix_ace_answer_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

## ACE Status Payload

`agentx ace-status SESSION --json` emits `agentx.ace_status.v1`.

This command is read-only. It summarizes one ACE session directory so external
runners can inspect manifest sections, open questions, briefing files, and
answer files without parsing markdown or scanning directories themselves.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.ace_status.v1`. |
| `ok` | boolean | True when the manifest was found and summarized. |
| `session_id` | string | Validated session id / directory name. |
| `root` | string | Resolved ACE root directory. |
| `session_dir` | string or null | Resolved session directory. |
| `manifest_path` | string or null | Resolved `_manifest.md` path. |
| `manifest_exists` | boolean | Whether `_manifest.md` exists. |
| `blockers` | array of string | Machine-readable blockers such as `manifest_not_found`. |
| `warnings` | array of string | Non-blocking diagnostics, including missing expected manifest sections. |
| `sections` | object | Manifest sections keyed by heading. |
| `section_entries` | object | Non-placeholder bullet entries keyed by heading. |
| `open_questions` | array of string | Non-placeholder bullets under `OPEN QUESTIONS`. |
| `briefings` | array of object | `briefing-*.md` file metadata: `name`, `path`, `size`, `mtime`. |
| `answers` | array of object | `answer-*.md` file metadata: `name`, `path`, `size`, `mtime`. |
| `counts` | object | Counts for briefings, answers, open questions, and section entries. |
| `manifest` | string | Manifest excerpt capped by `--max-manifest-chars`. |
| `manifest_truncated` | boolean | Whether the manifest excerpt was capped. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `ace_briefing` when open questions exist, `next` when ok, otherwise `fix_ace_status_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

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
| `latest_artifact` | object or null | First artifact after sorting by latest artifact mtime. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `handoff_resume`, `inspect_artifact`, or `headless_bundle`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
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

## Memory Status Payload

`agentx memory-status --json` emits `agentx.memory_status.v1`.

This command is read-only. It reports Memory Hall / AMH backend posture for
runners, including backend selection, namespace, AMH CLI availability,
store/path configuration, and token status. It never prints token values.
`--live-probe` runs a local AMH CLI availability probe.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.memory_status.v1`. |
| `ok` | boolean | False when the selected AMH backend is unusable, for example missing local CLI. |
| `workspace` | string | Resolved workspace path. |
| `namespace` | string | Resolved Memory Hall namespace. |
| `memory_backend` | string | Selected backend, usually `memhall` or `amh`. |
| `live_probe` | boolean | Whether `--live-probe` was requested. |
| `blockers` | array of string | Machine-readable blockers such as `amh_cli_unavailable` or `amh_cli_probe_failed`. |
| `warnings` | array of string | Non-blocking diagnostics such as `unknown_memory_backend`. |
| `legacy_memhall` | object | Legacy memhall URL and token status (`set` / `missing`). |
| `amh` | object | AMH command availability, binary paths, store, path, path existence for file stores, and optional `live_probe_result`. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | Suggested follow-up kind. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

## Memory Read Payload

`agentx memory-read QUERY --json` emits `agentx.memory_read.v1`.

This command queries Memory Hall / AMH through the configured backend. It is
read-only.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.memory_read.v1`. |
| `ok` | boolean | True when backend search completed. |
| `namespace` | string | Memory namespace queried. |
| `query` | string | Normalized query string. |
| `limit` | integer | Requested result limit. |
| `blockers` | array of string | Machine-readable blockers such as `query_required`. |
| `warnings` | array of string | Non-blocking diagnostics. |
| `result` | string | Backend search output. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | Suggested follow-up kind. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

## Memory Write Payload

`agentx memory-write CONTENT --json` emits `agentx.memory_write.v1`.

This command is dry-run by default and does not write memory unless `--write` is
explicitly provided. Written records use the ACA-shaped `tier` and `type`
arguments.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.memory_write.v1`. |
| `ok` | boolean | True when validation passed and, if requested, backend write completed. |
| `write` | boolean | Whether this invocation actually wrote memory. |
| `namespace` | string | Target memory namespace. |
| `memory_type` | string | ACA memory type such as `note`, `fact`, or `handoff`. |
| `tier` | string | ACA source tier such as `llm_derived` or `human_confirmed`. |
| `content_preview` | string | First 500 characters of content for auditability. |
| `content_truncated` | boolean | Whether content preview was capped. |
| `blockers` | array of string | Machine-readable blockers such as `content_required`, `invalid_tier`, or `invalid_memory_type`. |
| `warnings` | array of string | Non-blocking diagnostics such as `dry_run_no_memory_written`. |
| `memory_result` | object or null | Backend write result when `--write` is used. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | Suggested follow-up kind. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

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

## Task Update Payload

`agentx task-update ID STATUS [NOTES] --json` emits
`agentx.task_update.v1`.

The command updates exactly one task in `.agentx/tasks.json`. It is intended for
headless runners that need to close stale tasks or mark a task blocked without
entering the interactive `/task update` flow.

Supported `STATUS` values are `pending`, `in_progress`, `done`, and `blocked`.
Missing tasks and invalid statuses are reported as blockers. The command prints
the payload before exiting `1` when blockers are present.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.task_update.v1`. |
| `workspace` | string | Resolved workspace path. |
| `ok` | boolean | True when the task was updated. |
| `task_id` | integer | Requested task id. |
| `requested_status` | string | Raw status argument. |
| `status` | string | Normalized status. |
| `notes_updated` | boolean | True when notes were provided and the update succeeded. |
| `blockers` | array of string | `task_not_found` or `invalid_status`. |
| `warnings` | array of string | Non-blocking diagnostics such as `notes_truncated`. |
| `before` | object or null | Task object before mutation, or null when blocked. |
| `after` | object or null | Task object after mutation, or null when blocked. |
| `by_status` | object | Counts after the attempted update. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | `next` when ok, otherwise `fix_task_update_blockers`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested follow-up commands. |

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
| `recommended_command` | string | First suggested follow-up command for simple runners. Passing verification recommends `agentx review --json`; failures recommend fixing verification blockers and rerunning verify. |
| `recommended_kind` | string | `review` when checks pass, otherwise `fix_verify`. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
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
| `command_plan` | object or null | Embedded `agentx.command_plan.v1` for `run_command` / `run_build_command`, otherwise null. |
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

The catalog includes an `Infra preflight` recipe with aliases such as `infra`,
`vps`, `ssh`, and `deploy`. Its first step is `agentx infra resource-bundle
--json` and includes `command_plan`, so external runners can discover the
resource/home-AI/VPS preflight route before SSH, deploy, or cross-machine work.

The catalog also includes a `記憶交接` recipe with aliases such as `memory` and
`amh`, plus an `ACE council` recipe with aliases such as `ace`, `council`, and
`multi-agent`. These recipes expose the AMH read/dry-run/write handoff sequence
and the ACE manifest/briefing/answer/status sequence as command-plan annotated
runner steps.

Each workflow object includes:

| Key | Type |
|-----|------|
| `goal` | string |
| `path` | string |
| `steps` | array of object, each with `command`, `kind`, `runnable`, and optional `command_plan` for `agentx_cli` steps |
| `commands` | array of string, runnable steps extracted from `path` |
| `aliases` | array of string |

Step `kind` is one of `slash_command`, `agentx_cli`, or `instruction`.
`agentx_cli` steps include an embedded `agentx.command_plan.v1` payload so
runners can inspect policy posture before executing a top-level command.

## Workflow Plan Payload

`agentx workflow-plan NAME --json` emits `agentx.workflow_plan.v1`.

This command expands a single workflow recipe into an execution plan without
running any step. It is intended for external runners that need to collect
placeholder values and approval gates before executing a recipe.

Required stable keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema` | string | `agentx.workflow_plan.v1`. |
| `query` | string | Workflow name or alias requested. |
| `ok` | boolean | True only when the workflow exists and has no missing inputs or command-plan blockers. |
| `workflow` | object or null | Selected workflow catalog object. |
| `steps` | array of object | Ordered steps, each with `index`; runnable `agentx` steps include command plans. |
| `commands` | array of string | Runnable commands in execution order. |
| `inputs_required` | array of object | Placeholder inputs that must be filled before execution. |
| `side_effect_gates` | array of object | Steps with YELLOW/RED risk or approval requirements. |
| `command_blockers` | array of object | Per-step command-plan blockers. |
| `blockers` | array of string | Top-level blockers such as `workflow_not_found`, `missing_inputs`, or `command_plan_blockers`. |
| `warnings` | array of string | Non-blocking diagnostics such as side-effect gate reminders. |
| `recommended_command` | string | First suggested follow-up command for simple runners. |
| `recommended_kind` | string | Suggested follow-up kind. |
| `recommended_risk` | string | Risk label for the recommended follow-up. |
| `next_commands` | array of string | Suggested executable commands when the plan is ready, otherwise discovery commands. |

`--fail-on-blocker` prints the same payload first and exits `1` when `blockers`
is non-empty.

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
