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
agentx handoff-inspect tests/fixtures/headless_result_failure.json --field recovery_checklist
```

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
