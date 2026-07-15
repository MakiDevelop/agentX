# Objective Gap Audit: Codex/Grok-like agentX + AMH/ACE

**Date**: 2026-07-15
**Objective**: 將 agentX 優化到接近 Codex CLI / Grok CLI，並加入使用 AMH 與 ACE 的能力。
**Status**: In progress. AMH/ACE runner chain is now strongly covered; full objective is not yet proven complete.

## Current Evidence

### Runner-facing CLI foundation

- `agentx capabilities --json` exposes stable top-level automation commands, schemas, JSONL events, `recommended_entrypoints`, `by_schema`, and AMH/ACE `runner_smokes`.
- `agentx inspect --json` aggregates status, active tasks, sessions, approvals, traces, diff, capabilities, instructions, memory status, artifacts, next recommendations, verify commands, and command plans.
- `agentx next --json` provides deterministic next-step routing with embedded command plans.
- `agentx gate --json`, `review --json`, `commit-plan --json`, `verify --json`, `command-plan --json`, `tool-plan --json`, and `patch-check --json` provide runner-safe preflight surfaces.
- Deterministic headless benchmark covers a fresh `agentx -p ... --agent --artifact-dir ... --no-memory --json` run in a local fixture repo, including real tool write, result/session/handoff bundle, `artifacts`, `next`, and `gate`.

Evidence:
- `tests/test_capabilities_cli.py`
- `tests/test_headless_task_benchmark.py::test_headless_agent_benchmark_completes_task_artifacts_next_and_gate`
- `tests/test_inspect_cli.py`
- `tests/test_next_cli.py`
- `tests/test_gate_cli.py`
- `tests/test_command_plan_cli.py`
- `tests/test_tool_plan_cli.py`
- `docs/CLI_JSON_CONTRACTS.md`
- `docs/HEADLESS_OPTIMIZATION_LIST.md`

### AMH support

- `memory-status`, `memory-read`, and `memory-write` expose Memory Hall / AMH posture and read/write commands.
- `memory-write` is dry-run by default; explicit `--write` is required for external memory mutation.
- `workflows memory` exposes the AMH handoff route.
- `workflow-run memory --result-output ... --json` can save a workflow artifact.
- `artifacts`, `next`, `workflow-resume`, `doctor`, and `gate` can continue and observe the AMH workflow artifact chain.
- AMH dry-run runner smoke is discoverable through `capabilities.runner_smokes`.
- Isolated AMH local-store write smoke covers `memory-write --write`, `memory-read`, and `memory-status` using a workspace-local JSON store.
- `AmhClient` passes `--caller-ns <namespace>` for namespaced read/write/list operations, matching AMH namespace isolation.

Evidence:
- `tests/test_config_cli.py`
- `tests/test_config_cli.py::test_memory_amh_local_store_cli_smoke_writes_reads_and_reports_status`
- `tests/test_memory_hall.py`
- `tests/test_workflows_cli.py::test_memory_workflow_runner_smoke_links_artifact_next_resume_and_gate`
- `tests/test_capabilities_cli.py`
- `src/agentx/memory_hall.py`
- `docs/CLI_JSON_CONTRACTS.md`

### ACE support

- `ace-init`, `ace-append`, `ace-briefing`, `ace-answer`, and `ace-status` expose file-based ACE operations.
- `workflows ace` exposes the ACE council route.
- `workflow-run ace --result-output ... --json` can save a workflow artifact.
- `artifacts`, `next`, `workflow-resume`, `doctor`, and `gate` can continue and observe the ACE workflow artifact chain.
- ACE dry-run runner smoke is discoverable through `capabilities.runner_smokes`.
- Isolated ACE write smoke covers `ace-init --write`, `ace-briefing --write`, `ace-answer`, and `ace-status` using a pytest temporary ACE root.

Evidence:
- `tests/test_ace_cli.py`
- `tests/test_ace_cli.py::test_ace_write_cli_smoke_uses_temp_root_for_full_session_chain`
- `tests/test_workflows_cli.py::test_ace_workflow_runner_smoke_links_artifact_next_resume_and_gate`
- `tests/test_capabilities_cli.py`
- `docs/CLI_JSON_CONTRACTS.md`

## Remaining Gaps

### Gap 1: Live model reliability is not benchmarked

agentX now has a deterministic fake-backend benchmark that proves the runner chain. It does not prove reliability with real local models across a representative task suite, so "Codex/Grok-like" model-facing behavior remains partially unverified.

Suggested next proof:
- Add a small fixture task suite that can run against selected live or recorded backends.
- Track success/failure, tool-call count, termination, artifact completeness, and recovery recommendation quality.

### Gap 2: Interactive shell and runner JSON surfaces may drift

The objective compares agentX to CLI agents, but several capabilities exist mainly as top-level JSON commands. Some slash-command parity and interaction-flow parity still need explicit checks.

Suggested next proof:
- Add parity tests or a matrix linking slash command, top-level CLI command, schema, and risk posture.
- Start with AMH/ACE, artifacts, next, gate, and command-plan.

### Gap 3: Completion criteria are spread across multiple documents

The current evidence lives across README, CLI contracts, headless optimization list, roadmap, and tests. That is workable, but it makes the original objective hard to audit without re-reading many files.

Suggested next proof:
- Keep this audit updated as the objective checklist.
- Promote stable criteria into a short `docs/OBJECTIVE_STATUS.md` once Maki ratifies the target bar for "接近 Codex/Grok CLI".

## Recommended Next Slice

Implement an AMH/ACE slash-command parity matrix next. It should reduce drift between interactive shell flows and runner JSON surfaces:

```text
/config or /memory shell path
↔ memory-status/read/write JSON commands
↔ ace-init/briefing/answer/status JSON commands
```

Acceptance criteria:
- Documents command parity for AMH, ACE, artifacts, next, gate, and command-plan.
- Adds focused tests where command mappings are machine-checkable.
- Does not expand governance or external write behavior.
- Updates `docs/HEADLESS_OPTIMIZATION_LIST.md`.
