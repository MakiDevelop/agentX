# Objective Gap Audit: Codex/Grok-like agentX + AMH/ACE

**Date**: 2026-07-15
**Objective**: 將 agentX 優化到接近 Codex CLI / Grok CLI，並加入使用 AMH 與 ACE 的能力。
**Status**: In progress. AMH/ACE runner chain is now strongly covered; full objective is not yet proven complete.

Authoritative status page: `docs/OBJECTIVE_STATUS.md`.

## Current Evidence

### Runner-facing CLI foundation

- `agentx capabilities --json` exposes stable top-level automation commands, schemas, JSONL events, `recommended_entrypoints`, `by_schema`, and AMH/ACE `runner_smokes`.
- `agentx inspect --json` aggregates status, active tasks, sessions, approvals, traces, diff, capabilities, instructions, memory status, artifacts, next recommendations, verify commands, and command plans.
- `agentx next --json` provides deterministic next-step routing with embedded command plans.
- `agentx gate --json`, `review --json`, `commit-plan --json`, `verify --json`, `command-plan --json`, `tool-plan --json`, and `patch-check --json` provide runner-safe preflight surfaces.
- Deterministic headless benchmark covers a fresh `agentx -p ... --agent --artifact-dir ... --no-memory --json` run in a local fixture repo, including real tool write, result/session/handoff bundle, `artifacts`, `next`, and `gate`.
- `agentx command-parity --json` exposes a machine-readable slash-command to runner JSON matrix for AMH, ACE, artifacts, next, gate, and command-plan surfaces.
- `agentx reliability-suite --json` runs local-only recorded backend cases and scores headless artifacts, next, gate, artifact-resume / `handoff-resume`, recovery posture, termination, and tool-call counts.
- `agentx reliability-suite --json` includes `target_bar` (`agentx.reliability_target_bar.v1`), with proposed `recorded-v1` threshold: 4/4 cases, 100% pass rate, 0 failed cases, and all required checks passing.

Evidence:
- `tests/test_capabilities_cli.py`
- `tests/test_command_parity_cli.py`
- `tests/test_headless_task_benchmark.py::test_headless_agent_benchmark_completes_task_artifacts_next_and_gate`
- `tests/test_reliability_suite_cli.py`
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

agentX now has a deterministic fake-backend benchmark and a local recorded reliability suite covering edit, inspect, recover-after-failure, and artifact-resume. They do not prove reliability with real local models across a representative task suite, so "Codex/Grok-like" model-facing behavior remains partially unverified.

Suggested next proof:
- Add a live backend profile with pinned model/backend details, or have Maki ratify the proposed `recorded-v1` threshold if live proof is deferred.
- Track success/failure, tool-call count, termination, artifact completeness, and recovery recommendation quality.

### Gap 2: Completion criteria are spread across multiple documents

The current evidence lives across README, CLI contracts, headless optimization list, roadmap, and tests. That is workable, but it makes the original objective hard to audit without re-reading many files.

Suggested next proof:
- Keep `docs/OBJECTIVE_STATUS.md` updated as the objective checklist.
- Ratify the target bar for "接近 Codex/Grok CLI" and record the live/recorded reliability evidence there.

## Recommended Next Slice

Ratify or replace the reliability target bar next:

```text
recorded-v1 threshold proposal
→ Maki ratification or pinned live backend profile
→ OBJECTIVE_STATUS update
```

Acceptance criteria:
- Runs local-only by default.
- Records whether `recorded-v1` is ratified, replaced, or superseded by a pinned live backend profile.
- Updates `docs/OBJECTIVE_STATUS.md`.
- Updates `docs/HEADLESS_OPTIMIZATION_LIST.md`.
