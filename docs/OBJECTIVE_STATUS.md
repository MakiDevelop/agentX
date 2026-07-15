# Objective Status: Codex/Grok-like agentX + AMH/ACE

**Date**: 2026-07-15
**Objective**: 將 agentX 優化到接近 Codex CLI / Grok CLI，並加入使用 AMH 與 ACE 的能力。
**Status**: Complete for the ratified recorded-v1 target. Runner mechanics, AMH support, ACE support, recorded reliability suite, artifact-resume coverage, pinned live profile inspection, live suite execution surface, decision artifact support, and read-only objective gate are covered. The local decision artifact ratifies recorded-v1 evidence; live-v1 remains an optional stronger future proof, not a blocker for this objective.

This file is the single ratifiable status page for the objective. `docs/OBJECTIVE_GAP_AUDIT_2026-07-15.md` remains the detailed audit trail.

## Target Requirements

The objective is treated as complete only when all of these are true:

1. **Runner-facing CLI foundation**: external runners can discover commands, schemas, events, next steps, gates, command preflight, artifacts, and local instructions without parsing human prose.
2. **Headless task execution**: `agentx -p ... --agent` can complete a representative engineering task end-to-end and produce usable result/session/handoff artifacts.
3. **AMH support**: agentX can inspect, read, dry-run write, explicitly write, and workflow-chain AMH handoff behavior with namespace isolation.
4. **ACE support**: agentX can create/preview ACE sessions, write scoped briefings, record answers, summarize status, and workflow-chain ACE coordination behavior.
5. **Safety posture**: write paths are explicit, default-safe, local/testable where possible, and runner preflight does not mutate.
6. **Parity/discovery**: shell-oriented flows and runner JSON surfaces have a machine-readable mapping for critical AMH/ACE/artifact/gate routes.
7. **Reliability bar**: selected live or recorded backend tasks pass a ratified benchmark suite with artifact completeness, sensible termination, and usable recovery recommendations.

## Proven Now

### Runner Mechanics

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

Current proof:
- `agentx capabilities --json` exposes stable runner command discovery, schemas, JSONL events, recommended entrypoints, schema lookup, and AMH/ACE runner smokes.
- `agentx inspect --json` aggregates workspace status, tasks, sessions, approvals, traces, diff, capabilities, instructions, memory status, artifacts, next recommendations, verify commands, and command plans.
- `agentx next --json`, `gate --json`, `review --json`, `commit-plan --json`, `verify --json`, `command-plan --json`, `tool-plan --json`, and `patch-check --json` provide runner-safe preflight and routing.
- Deterministic headless benchmark proves the runner chain using fake backend + local fixture repo: real tool write, result/session/handoff bundle, `artifacts`, `next`, and `gate`.
- `agentx command-parity --json` maps critical slash-command families to runner JSON surfaces.
- `agentx reliability-suite --json` runs a local-only recorded backend suite and scores exit code, termination, tool-call count, artifact completeness, expected files, `next`, `gate`, artifact-resume / `handoff-resume`, and recovery recommendation posture.
- The same payload now includes `target_bar` (`agentx.reliability_target_bar.v1`). The ratified `recorded-v1` target requires 4/4 cases, 100% pass rate, 0 failed cases, and all required checks passing.
- `agentx reliability-profile --json` emits `agentx.reliability_profile.v1`, a pinned backend/model/base URL profile for later live reliability evidence. It is read-only by default; `--live-probe` explicitly verifies model availability.
- `agentx reliability-suite --suite-kind live --json` can run the same fixture threshold against a pinned backend/model and emit `live-v1` observed target-bar evidence.
- `agentx reliability-decision --json` emits `agentx.reliability_decision.v1`, a write-gated decision artifact surface. The workspace-local decision artifact ratifies recorded-v1 evidence from `.agentx/reliability/codex-decision-smoke-suite.json`.
- `agentx objective-gate --json` emits `agentx.objective_gate.v1`, checking required AMH/ACE/reliability CLI surfaces plus the accepted/ratified reliability decision artifact; current output reports `completion_ready=true`.

### AMH

Evidence:
- `tests/test_config_cli.py::test_memory_amh_local_store_cli_smoke_writes_reads_and_reports_status`
- `tests/test_memory_hall.py`
- `tests/test_workflows_cli.py::test_memory_workflow_runner_smoke_links_artifact_next_resume_and_gate`
- `tests/test_capabilities_cli.py`
- `src/agentx/memory_hall.py`
- `docs/CLI_JSON_CONTRACTS.md`

Current proof:
- `memory-status`, `memory-read`, and `memory-write` expose JSON surfaces.
- `memory-write` is dry-run unless `--write` is explicit.
- Isolated local-store smoke proves `memory-write --write -> memory-read -> memory-status`.
- `AmhClient` passes `--caller-ns <namespace>` for namespaced operations.
- AMH workflow dry-run artifact chain is discoverable through `capabilities.runner_smokes`.

### ACE

Evidence:
- `tests/test_ace_cli.py::test_ace_write_cli_smoke_uses_temp_root_for_full_session_chain`
- `tests/test_workflows_cli.py::test_ace_workflow_runner_smoke_links_artifact_next_resume_and_gate`
- `tests/test_capabilities_cli.py`
- `docs/CLI_JSON_CONTRACTS.md`

Current proof:
- `ace-init`, `ace-append`, `ace-briefing`, `ace-answer`, and `ace-status` expose file-based ACE operations.
- Isolated temp-root smoke proves `ace-init --write -> ace-briefing --write -> ace-answer -> ace-status`.
- ACE workflow dry-run artifact chain is discoverable through `capabilities.runner_smokes`.

## Limits

### Live Model Reliability

The deterministic fake-backend benchmark and recorded reliability suite prove runner mechanics and replayable recorded behavior, not broad live model quality. A future live-v1 benchmark can strengthen confidence against a pinned local model/backend, but recorded-v1 has been ratified for this objective.

### Final Target Bar

The `recorded-v1` pass threshold is machine-readable in `agentx reliability-suite --json` and ratified by `.agentx/reliability/decision.json`. `agentx reliability-profile --json` can pin live backend details; `agentx reliability-suite --suite-kind live --json` can produce observed `live-v1` evidence if Maki wants a stronger future benchmark.

## Completion Gate

The objective is complete when:

1. `uv run pytest -q` and `uv run ruff check .` pass.
2. `agentx capabilities --json` exposes runner discovery for headless, AMH, ACE, parity, next, gate, and command-plan surfaces.
3. AMH isolated local-store write/read/status smoke passes.
4. ACE isolated temp-root write/status smoke passes.
5. Headless deterministic benchmark passes.
6. Live or recorded reliability suite passes the ratified target threshold and has a valid decision artifact. Current recorded suite covers edit, inspect, recover-after-failure, and artifact-resume; recorded-v1 is ratified by `.agentx/reliability/decision.json`.
7. `agentx objective-gate --json` reports `completion_ready=true`.
8. This file records the benchmark evidence and current `Complete` status.

## Optional Next Slice

Strengthen live model evidence:

```text
live benchmark run via pinned reliability profile
-> reliability-decision --profile live-v1 --decision accepted --write
-> objective-gate --json
-> OBJECTIVE_STATUS update
```

Keep this future slice local-only and non-destructive. It should not deploy, SSH, touch production, or write external memory by default.
