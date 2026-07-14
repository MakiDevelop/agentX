# Headless Payload Contract

This document defines the stable machine-readable contract for `agentx -p ...
--agent --json`, `agentx ask ... --json`, and `--output-format jsonl`.

The goal is to let Codex/Grok-style runners, CI jobs, and other agents consume
agentX headless results without parsing natural language output.

## Compatibility Rules

- Existing keys listed here are append-only. Do not remove or rename them without
  an explicit migration note and test update.
- New keys may be added at any object level.
- Consumers should ignore unknown keys.
- `schema_version` identifies the result payload contract. Current value:
  `agentx.headless_result.v1`.
- `log_summary.handoff_summary` is the preferred takeover object after a failed,
  timed out, or max-steps run.
- All handoff fields are deterministic runtime state. They must not require an
  additional model call.
- Checklist fields are non-destructive guidance. They must not instruct direct
  `rm`, reset, deploy, production write, or other irreversible operations.

## Top-Level Result Payload

Required keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema_version` | string | Stable contract marker. Current value: `agentx.headless_result.v1`. |
| `output` | string | Final natural-language output for humans. |
| `exit_code` | integer | Process-compatible outcome code. |
| `termination` | string | Structured termination reason. |
| `failing_tools` | array of string | Tools with unresolved failures. |
| `stats` | object | Runtime counters and task counts. |
| `log_summary` | object | Machine-readable execution summary. |
| `session_path` | string or null | Saved or resumed session JSONL path, if available. |

Optional keys:

| Key | Type | Meaning |
|-----|------|---------|
| `phases` | array of object | Present for plan-then-execute results. |

## JSONL Envelope

`--output-format jsonl` emits one JSON object per line. For normal headless runs:

```json
{"event":"result","data":{"termination":"final_success"}}
```

Other events currently include `dry_run`, `version`, `backends`, and `models`.
Consumers should branch on `event` and read the payload from `data`.

A failure takeover fixture is kept at
`tests/fixtures/headless_result_failure.json`. Runner integrations can use it as
a stable example for extracting `data.log_summary.handoff_summary.resume_command`
and `data.log_summary.handoff_summary.recovery_checklist`.

For a local inspection helper:

```bash
agentx handoff-inspect tests/fixtures/headless_result_failure.json
agentx handoff-inspect tests/fixtures/headless_result_failure.json --output-format jsonl
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command --next-prompt "照上一輪繼續"
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command --next-prompt-file .agentx/handoff/next.md
agentx handoff-inspect tests/fixtures/headless_result_failure.json --briefing-output .agentx/handoff/next.md --next-prompt-file .agentx/handoff/next.md --field resume_command
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command --resume-output-format jsonl
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command --use-payload-exit-code
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field resume_command --require-handoff
agentx handoff-inspect tests/fixtures/headless_result_failure.json --require-schema-version
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field recovery_checklist
agentx -p "..." --agent --output-format jsonl | agentx handoff-inspect - --field resume_command --next-prompt "照上一輪繼續" --use-payload-exit-code
agentx handoff-resume .agentx/runs/latest
agentx handoff-resume .agentx/runs/latest --resume-output-format jsonl
agentx handoff-resume .agentx/runs/latest --dry-run
agentx handoff-resume .agentx/runs/latest --execute
agentx handoff-resume tests/fixtures/headless_result_failure.json --next-prompt "照上一輪繼續"
```

`--use-payload-exit-code` is opt-in. Without it, `handoff-inspect` exits zero
after a successful inspection even when the inspected payload represents a
failed headless run. With it, the command prints the requested takeover data and
then exits with the payload `exit_code` clamped to the shell range `0..255`.
`--require-handoff` is a runner gate: it exits 1 unless the inspected payload has
`needs_handoff=true` and a non-empty `resume_command`. The command still prints
the requested inspection output before exiting.
`--require-schema-version` is a compatibility gate: it exits 1 unless
`schema_version` matches the current contract version.
`--next-prompt-file PATH` rewrites the generated `resume_command` to use
`--prompt-file PATH` instead of `-p '<next prompt>'`; it is mutually exclusive
with `--next-prompt`.
`--briefing-output PATH` writes a deterministic Markdown takeover briefing inside
the current workspace and refuses to overwrite an existing file. It is useful
with `--next-prompt-file PATH` so the printed `resume_command` points at the same
artifact that was just created.
`--resume-output-format json|jsonl` rewrites the generated `resume_command`
output mode. Use `jsonl` when the next runner expects event envelopes.
`handoff-resume SOURCE` prints only the generated `resume_command`. If `SOURCE`
is an artifact bundle directory, it reads `result.json` or `result.jsonl` and
uses `handoff.md` as the default `--prompt-file` when present. If `SOURCE` is a
payload file, it behaves like `handoff-inspect --field resume_command`.
`--dry-run` prints the final command and argv without running it; `--execute`
explicitly runs the generated command and exits with the child process status.

For automation that needs a stable artifact path instead of stdout parsing:

```bash
agentx -p "..." --agent --result-output .agentx/results/run.json --quiet
agentx -p "..." --agent --output-format jsonl --result-output .agentx/results/run.jsonl
agentx -p "..." --agent --result-output .agentx/results/run.jsonl --result-output-format jsonl
agentx -p "..." --agent --handoff-briefing-output .agentx/handoff/next.md --quiet
agentx -p "..." --agent --artifact-dir .agentx/runs/latest --quiet
agentx ask "..." --result-output .agentx/results/ask.json --quiet
agentx ask "..." --handoff-briefing-output .agentx/handoff/ask-next.md --quiet
agentx ask "..." --artifact-dir .agentx/runs/ask-latest --quiet
```

`--result-output` writes inside the active workspace only, refuses to overwrite
an existing file, and creates parent directories as needed. With plain stdout the
artifact is JSON. With `--output-format jsonl` the artifact is the same single
`result` event envelope that can be passed to `agentx handoff-inspect`.
`--result-output-format auto|json|jsonl` can decouple artifact format from
stdout format; `auto` keeps the default behavior.
`--handoff-briefing-output PATH` writes the same deterministic Markdown takeover
briefing during the original headless run, without requiring a follow-up
`handoff-inspect` command. The path must stay inside the active workspace,
parents are created as needed, existing files are rejected, and it must be
distinct from `--session-output` and `--result-output`.
`--artifact-dir DIR` is the standard bundle preset for external runners. It
writes these files under `DIR`:

- `session.session.jsonl`
- `result.json` or `result.jsonl`, depending on `--result-output-format`
- `handoff.md`

It requires agent mode, is mutually exclusive with individual artifact output
options, and rejects any pre-existing standard bundle file.

## `log_summary`

Required keys:

| Key | Type | Meaning |
|-----|------|---------|
| `termination` | string | Mirrors the structured termination reason. |
| `tool_outcomes` | object | Tool name to boolean success status. |
| `successful_tools` | array of string | Tools that completed successfully. |
| `failing_tools` | array of string | Tools that still need attention. |
| `recent_errors` | array of object | Last errors, newest last. |
| `recovery_suggestions` | array of object | Structured playbook suggestions. |
| `pending_verifies` | array of string | Edited paths still requiring verification. |
| `handoff_summary` | object | Self-contained takeover summary. |

## `handoff_summary`

Required keys:

| Key | Type | Meaning |
|-----|------|---------|
| `status` | string | Same semantic value as `termination`. |
| `needs_handoff` | boolean | True when another run or agent should continue work. |
| `failing_tools` | array of string | Unresolved failing tools. |
| `pending_verifies` | array of string | Paths requiring verification before further edits. |
| `task_counts` | object | Counts by task status. |
| `last_error` | object or null | Most recent error context. |
| `recovery_actions` | array of string | Ordered recovery action names. |
| `primary_recovery` | object or null | Highest-priority recovery suggestion. |
| `recovery_checklist` | array of string | Deterministic, non-destructive next checks. |
| `next_steps` | array of string | Human/agent-readable takeover steps. |
| `session_path` | string or null | Session path copied from top-level payload. |
| `resume_session` | string or null | Session filename suitable for `--resume-session`. |
| `resume_command` | string or null | Copyable resume command when a session is available. |

`recovery_checklist` should be used before any new code edit after failure. It
is intentionally command-agnostic so the next agent can choose local tools while
preserving the same recovery intent.

## Resume Contract

When `session_path` is available, `handoff_summary.resume_command` must point to
the same session by filename:

```bash
agentx -p '<next prompt>' --agent --resume-session <session-file> --json
```

The command is a scaffold. The caller should replace `<next prompt>` with the
actual continuation prompt.
