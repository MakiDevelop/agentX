# Objective Gap Audit: Codex/Grok-like agentX + AMH/ACE

**Date**: 2026-07-15
**Objective**: 將 agentX 優化到接近 Codex CLI / Grok CLI，並加入使用 AMH 與 ACE 的能力。
**Status**: Complete for the ratified recorded-v1 target. AMH/ACE runner chain, runner-facing CLI foundation, recorded reliability evidence, and objective gate are proven complete. Live-v1 remains optional stronger evidence.

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
- `agentx reliability-profile --json` includes pinned backend/model/base URL details for later live benchmark evidence; `--live-probe` explicitly verifies model availability.
- `agentx reliability-suite --suite-kind live --json` can run the same fixture threshold against a pinned backend/model and emit observed `live-v1` target-bar evidence.
- `agentx reliability-decision --json` can preview or write a reliability decision artifact, requiring matching threshold-passing evidence for `ratified` / `accepted` decisions.
- `agentx objective-gate --json` can read-only check required command surfaces and the reliability decision artifact for completion readiness, and can recommend a concrete decision command from the latest threshold-passing suite evidence.

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

## Remaining Limits

### Limit 1: Live model reliability is not benchmarked

agentX now has a deterministic fake-backend benchmark, a local recorded reliability suite covering edit, inspect, recover-after-failure, and artifact-resume, a pinned live profile inspection command, a live suite execution surface, a decision artifact surface, and an objective gate. The workspace-local decision artifact ratifies recorded-v1 evidence, so this is no longer a completion blocker. It still does not prove broad live model quality.

Suggested future proof:
- Run and accept a live backend benchmark using a pinned `agentx reliability-profile --json --live-probe` profile, then write the decision through `agentx reliability-decision --write`.
- Track success/failure, tool-call count, termination, artifact completeness, and recovery recommendation quality.

### Limit 2: Completion criteria are spread across multiple documents

The current evidence lives across README, CLI contracts, headless optimization list, roadmap, tests, `.agentx/reliability/codex-decision-smoke-suite.json`, and `.agentx/reliability/decision.json`. `docs/OBJECTIVE_STATUS.md` is the single status page, but deep audits still need to inspect those sources.

Suggested future proof:
- Keep `docs/OBJECTIVE_STATUS.md` updated as the objective checklist when live-v1 evidence or new target bars are added.

## Optional Next Slice

Add live-v1 evidence:

```text
live benchmark run via pinned reliability profile
→ reliability-decision --profile live-v1 --decision accepted --write
→ objective-gate --json
→ OBJECTIVE_STATUS update
```

Acceptance criteria:
- Runs local-only by default.
- Records whether `live-v1` supersedes the current recorded-v1 benchmark against a pinned reliability profile through a valid decision artifact.
- Updates `docs/OBJECTIVE_STATUS.md`.
- Updates `docs/HEADLESS_OPTIMIZATION_LIST.md`.
