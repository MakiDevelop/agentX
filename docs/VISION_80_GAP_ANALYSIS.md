# agentX Vision 80% Gap Analysis

**Date**: 2026-05-25  
**Purpose**: Track the gap between the 5 product-vision images and the current CLI implementation.  
**Status**: Phase 1 product-surface pass completed in commit `4463c71`; `/guide` and richer `/sessions` added in the next pass.

## Summary

The 5 images describe a polished local Ollama agent shell with three clear modes, rich tools, Memory Hall continuity, and safety as an everyday visible feature.

agentX already has most of the core engineering pieces:

- `chat` / `ask` / `shell` modes
- Slash commands for files, search, git, diff, tests, Docker, Memory Hall, sessions, resume, handoff, context, and tasks
- GREEN / YELLOW / RED risk model with approval policy
- Transcript-backed resume and auto handoff
- Task list persistence and MT22 migration work

The largest remaining gap is product experience: discoverability, onboarding, and making safety feel reassuring instead of hidden.

## Current Estimate

| Dimension | Current | Notes |
|---|---:|---|
| Engineering capability | 80-85% | Strong CLI/tool/runtime foundation. |
| Feature completeness | 75-80% | Most pictured functions exist in some form. |
| Safety communication | 70-75% | Improved in `/help`, `/tools`, `/doctor`, `/status`, welcome UI. |
| Memory continuity feeling | 65-70% | Handoff/resume exist; UX can still feel technical. |
| Onboarding / first 60 seconds | 60-70% | Better welcome/help surfaces; no true first-run wizard yet. |
| Visual polish | 55-65% | Rich panels help, but this is still terminal-first. |

Overall: roughly **75-80% on the read-heavy / guarded MVP vision**, with the next gains coming from onboarding and continuity rather than more tools.

## What Was Completed

Recent product-surface passes moved the daily UX surfaces closer to the images:

- `/guide` gives a 60-second orientation across modes, workflows, safety, and Memory Hall.
- `/help` is categorized by workflow instead of a flat list.
- `/tools` groups tools by GREEN / YELLOW / RED risk.
- `/doctor` now shows both technical health and product posture.
- `/status` shows approval mode and safety meaning.
- Shell welcome text now states the local Ollama agent-shell positioning and safety model.
- `/run` output includes final command and per-argument listing.
- `/resume latest` no longer resumes the current empty transcript.
- Handoff uses the latest task list snapshot.
- Safety command classification catches sensitive paths and cross-absolute-path `mv`.
- README now reflects `task`, `approval`, and `execute` behavior.

Validation for that commit:

- `uv run ruff check .`
- `uv run pytest -q` (`149 passed`)
- `uv run agentx --help`

## Remaining Gaps

### P0: Avoid Agent Loop Drift

The previous autonomous pass kept appending "continue / no stopping" status blocks to this document. That pattern is explicitly not useful. Future work should be scoped into small commits with tests or clear acceptance criteria.

### P1: First-Run / Orientation

New users still need to infer the best entry point.

Recommended next work:

- Keep refining `/guide` with real user feedback.
- Add a first-run hint that does not repeat every launch once dismissed.

### P1: Memory Hall Felt Continuity

The mechanics exist, but the experience is still technical.

Recommended next work:

- Continue improving `/sessions` summaries and resume affordances.
- Make `/resume latest` print what was loaded.
- Improve `/handoff` output with clearer next-step sections.

### P2: Approval Gate UX

The approval model works, but terminology is still a little CLI-native.

Recommended next work:

- Consider `strict` and `deny` aliases while keeping existing `ask/auto/off` stable.
- Add examples to `/approval`.
- Show when a YELLOW tool was auto-approved vs manually approved in transcript.

### P2: Visual Polish

Panels and risk grouping improved the terminal experience. Full parity with the images would require a deliberate TUI pass.

Recommended next work:

- Stable layout tests for help/tools output.
- Fewer repeated safety footers.
- Better compact display for narrow terminals.

## Non-Goals For The Next Pass

- Do not rewrite the TUI architecture.
- Do not change RED behavior without explicit human approval.
- Do not remove MT22 legacy task support until the migration gates are met.
- Do not keep appending speculative percentage updates after every micro-change.

## Recommended Next Unit

Improve resume/handoff continuity as a small, testable unit:

- Make `/resume latest` print the transcript name and loaded summary size.
- Add clearer "next steps" formatting to `/handoff`.
- Keep output concise enough for narrow terminals.
- Cover the transcript summary behavior with focused tests.
