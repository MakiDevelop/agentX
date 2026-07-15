# Objective Status: Codex/Grok-like agentX + AMH/ACE

**Date**: 2026-07-15
**Objective**: 將 agentX 優化到接近 Codex CLI / Grok CLI，並加入使用 AMH 與 ACE 的能力。
**Status**: In progress. Runner mechanics, AMH support, and ACE support are strongly covered; live/recorded model reliability is not yet proven.

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

## Not Proven Yet

### Live/Recorded Model Reliability

The deterministic fake-backend benchmark proves runner mechanics, not model quality. It does not prove that real local models can reliably perform Codex/Grok-like tasks across a representative benchmark suite.

Required next evidence:
- A small fixture task suite with at least edit, inspect, recover-after-failure, and artifact-resume scenarios.
- A deterministic recorded-backend mode, or a live backend run profile with pinned model/backend details.
- Metrics for success/failure, tool-call count, termination, artifact completeness, gate/next quality, and recovery recommendation usefulness.

### Final Target Bar

The exact pass threshold for "接近 Codex/Grok CLI" still needs Maki ratification. Until that bar is ratified and verified, the full objective remains in progress.

## Completion Gate

Do not mark the objective complete until:

1. `uv run pytest -q` and `uv run ruff check .` pass.
2. `agentx capabilities --json` exposes runner discovery for headless, AMH, ACE, parity, next, gate, and command-plan surfaces.
3. AMH isolated local-store write/read/status smoke passes.
4. ACE isolated temp-root write/status smoke passes.
5. Headless deterministic benchmark passes.
6. Live or recorded reliability suite passes the ratified target threshold.
7. This file is updated with the benchmark evidence and status changes from `In progress` to `Complete`.

## Recommended Next Slice

Build the live/recorded backend reliability suite:

```text
fixture tasks
-> recorded or selected live backend
-> headless artifact bundle
-> next/gate/recovery evaluation
-> score summary
```

Keep the first version local-only and non-destructive. It should not deploy, SSH, touch production, or write external memory by default.
