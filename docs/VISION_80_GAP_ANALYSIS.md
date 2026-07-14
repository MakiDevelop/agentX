# agentX Vision 80% Progress

**Date**: 2026-05-25  
**Purpose**: Track progress toward the 5 product-vision images and define the next implementation queue.  
**Current status**: ~82-85% of the read-heavy / guarded MVP vision.  
**Memory Hall**: `project:agentX` entry `01KSEBHDM4RX5112ZV65JN0VD9`

This document is intentionally concrete. It should prevent future agents from looping on vague "keep improving polish" work. Each next item should be implemented as a small, testable commit.

## Vision Target

The 5 images describe a local Ollama agent shell with:

- A clear first impression: "本地 Ollama agent shell"
- Three understandable use modes: `chat`, `ask`, `shell`
- Rich slash-command workflows for files, git, tests, review, Docker, Memory Hall, context, and commit
- Memory Hall + transcript continuity across sessions
- Safety as a visible product feature: GREEN / YELLOW / RED, approval gates, user control

agentX already has most of the runtime capability. The remaining work is primarily product experience, naming consistency, and handoff quality.

## Completed Commits

| Commit | Title | What changed |
|---|---|---|
| `4463c71` | 補強 agentX 安全與 shell 完整度 | Categorized `/help`, risk-grouped `/tools`, richer `/doctor` and `/status`, safer `/resume latest`, fresh task snapshots for handoff, final command/args preview for `/run`, stronger safety classification, full ruff/pytest cleanup. |
| `e06f8e0` | 收斂 Grok 文件與本地狀態忽略規則 | Replaced loop-prone Grok progress notes with a concise Vision tracker; ignored local `.agentx` state, tmp files, and Gemini symlink. |
| `c5c96b7` | 新增 guide 導覽與 session 摘要 | Added `/guide` 60-second orientation; richer `/sessions` view with start/model/namespace/turns/last summary; README and tests updated. |
| `b1b1fcd` | 改善 resume 與 handoff 交接體驗 | `/resume` now reports loaded transcript name/source/summary size/next hint; `/handoff` now includes active-task next steps; tests added. |
| `458e7ed` | 新增一次性 guide 啟動提示 | Added local-only `.agentx/state.json`; first launch in a repo shows `/guide` hint once, then dismisses locally; tests and docs updated. |
| current unit | 補齊 mode/approval/workflow/product tour | Added `/mode ask`, approval aliases (`strict`, `auto-approve`, `deny`), deterministic handoff sections, `/workflows`, product tour doc, README/tests updates. |

## Verification Baseline

Latest verified baseline after `458e7ed`:

- `uv run ruff check .` passed
- `uv run pytest -q` passed: `158 passed`
- Shell smoke: temporary workspace showed first-run guide hint once, second launch suppressed it, `.agentx/state.json` contained `{"guide_hint_seen": true}`

Known warning noise:

- `tests/test_task.py` and `tests/test_tasks.py` still emit MT22 deprecation warnings for legacy task APIs. This is expected until MT22 migration/removal is finished.

## Image-by-Image Status

### Image 1: Hero / Local Ollama Agent Shell

**Current estimate**: 80%

Done:

- README now opens with a clear local Ollama agent-shell positioning.
- Shell welcome panel states model, mode, workspace, namespace, and safety model.
- One-time first-run `/guide` hint gives a concrete onboarding path.
- `/guide` explains what agentX is and how to start.

Remaining gap:

- No visual landing page or demo artifact matching the polish of the images.
- README is usable but still documentation-first, not product-page-polished.

Recommended next:

- Add `docs/demo.md` or `docs/product-tour.md` with screenshots / terminal captures.
- Keep README concise and link to deeper tour rather than expanding endlessly.

### Image 2: Three Modes, From Simple to Powerful

**Current estimate**: 85%

Done:

- Top-level commands exist: `agentx chat`, `agentx ask`, `agentx shell`.
- `/guide` explains `chat`, `ask`, `shell` with examples.
- Shell supports mode switching through `/mode chat` and `/mode agent`.
- Plan/execute flow exists for higher-risk or complex work.

Remaining gap:

- Image uses `chat / ask / shell`, but shell-internal naming still uses `/mode agent`.
- No `/mode ask` alias yet.
- No explicit "ask mode = one-shot agent task" alias inside shell.

Recommended next:

- Add `/mode ask` as an alias for current shell `agent` mode, while preserving `/mode agent`.
- Update `/guide`, `/help`, README, and tests so mode language matches the image.

### Image 3: Tools, Workflows, Risk Cards

**Current estimate**: 80-85%

Done:

- Tools cover files, read, search, fetch, git, diff, tests, review, Docker Compose, Memory Hall, patch/edit helpers, context, sessions, commit.
- `/tools` groups by GREEN / YELLOW / RED.
- `/help` groups slash commands by workflow category.
- `/guide` provides common workflows: understand project, inspect changes, safe execution, resume/handoff.
- `/run` prints final command and per-argument listing.

Remaining gap:

- No dedicated `/workflows` or deeper workflow helper.
- Tool output is Rich-terminal-polished but not visual-card-polished like the images.
- No layout tests for help/tools narrow terminal output.

Recommended next:

- Either extend `/guide` with a "full" mode or add `/workflows`.
- Add tests for `SLASH_COMMANDS` coverage and guide workflow content.
- Avoid adding decorative complexity unless it improves actual discoverability.

### Image 4: Memory Hall + Session Handoff

**Current estimate**: 78-82%

Done:

- `/memory` and `/remember` work through Memory Hall.
- `/sessions` shows transcript name/start/model/namespace/turns/last.
- `/resume latest` excludes the current empty transcript.
- `/resume` reports loaded transcript name, source, summary lines, approximate tokens, and next hint.
- `/handoff` includes task-aware next steps.
- Auto handoff uses fresh task snapshots.

Remaining gap:

- Handoff is still heuristic and mechanical.
- It does not yet always produce clean sections for completed / todo / blockers / next agent.
- `/sessions` last summary is useful but still lightweight.

Recommended next:

- Improve `build_handoff()` structure:
  - `完成`
  - `待辦`
  - `阻塞`
  - `下一輪建議`
- Keep it deterministic first. Do not call a model for handoff unless reliability and timeout behavior are clear.
- Add tests for handoff section formatting.

### Image 5: Safety Priority + Approval Gate

**Current estimate**: 89%

Done:

- GREEN / YELLOW / RED risk classification exists and is visible in `/tools`, `/help`, `/doctor`, `/status`, welcome UI.
- Approval policy supports `ask`, `auto`, `off`, plus aliases `strict`, `auto-approve`, and `deny`.
- Transcript and headless `log_summary.approval_receipts` distinguish YELLOW `auto_approved`, `manual_approved`, `manual_denied`, and `policy_denied` decisions.
- `/sessions` overview surfaces approval receipt counts and denied counts; `/transcript approvals latest|SESSION --denied` drills into current and historical receipt lists.
- RED tools are blocked.
- Dangerous command patterns and sensitive paths are guarded.
- Cross-absolute-path `mv` is conservatively RED.
- `/run` is allowlisted and prints command preview.
- Docker build/up/down are YELLOW and preview final command/args.

Remaining gap:

- Approval receipt drill-down is textual and can filter denied receipts, but does not filter by tool/source yet.

Recommended next:

- Consider tool/source filters only if denied-only still becomes noisy.
- Keep RED behavior unchanged.

## Current Gap Summary

| Area | Status | Next best unit |
|---|---:|---|
| Local shell positioning | 80% | Product tour doc / demo capture |
| Mode clarity | 85% | `/mode ask` alias |
| Tool discoverability | 80-85% | `/workflows` or `/guide --full` |
| Memory continuity | 78-82% | Handoff section formatting |
| Safety / approval UX | 92% | Optional tool/source filters |
| Visual polish | 55-65% | Optional TUI/web demo, not required for guarded MVP |

## Recommended Implementation Queue

### P0: Mode and Approval Naming Alignment

Small, safe, high-value naming changes:

1. Add `/mode ask` alias for shell agent mode.
2. Add approval aliases:
   - `/approval auto-approve`
   - `/approval strict`
   - `/approval deny`
3. Allow `.agentx/config.toml` `approval = "auto-approve" | "strict" | "deny"` by normalizing to canonical values.
4. Update README and tests.

Acceptance:

- Done in current unit.
- Existing `ask/auto/off` behavior remains compatible.
- RED behavior unchanged.
- `uv run ruff check .` and `uv run pytest -q` pass.

### P1: Handoff Section Formatting

Make deterministic handoff easier for the next session/agent to parse.

Acceptance:

- Done in current unit.
- Handoff includes sections for completed / active todo / blockers / next suggested command.
- Existing Memory Hall write path unchanged.
- Tests verify section headings and active-task rendering.

### P1: Workflow Helper

Choose one:

- Extend `/guide` with more workflow rows, or
- Add `/workflows` for practical recipes.

Acceptance:

- Done in current unit with `/workflows`.
- User can see how to do "understand project", "modify safely", "review", "handoff".
- Tests cover command registration and key workflow strings.

### P2: Product Tour / Demo Doc

Add a documentation artifact that maps directly to the five images.

Acceptance:

- Done in current unit with `docs/product-tour.md`.
- `docs/product-tour.md` or `docs/demo.md`.
- Includes minimal terminal examples and links to `/guide`, `/tools`, `/sessions`, `/approval`.
- Avoids pretending there is a web UI if there is not.

## Explicit Non-Goals

- Do not rewrite TUI architecture unless Maki explicitly asks.
- Do not change RED behavior without explicit approval.
- Do not remove MT22 legacy task support until migration gates are met.
- Do not keep appending vague percentage updates after every micro-change.
- Do not commit local `.agentx/state.json`, sessions, patches, or tmp files.

## Suggested Next Commit

Maki's next requested direction is tracked in `docs/CAPABILITY_ROADMAP_2026-05-25.md`:

1. Local file retrieval by keyword/topic
2. Git operation loop
3. Intent understanding and task decomposition

Recommended implementation order is search first, then Git, then intent understanding. Search and Git are the reliability foundation; intent understanding should become a thin task-planning layer on top of those capabilities.

After that roadmap, the next useful polish-only commit should focus on either:

- narrow-terminal layout tests for `/help`, `/tools`, `/guide`, `/workflows`
- richer transcript distinction for manually approved vs auto-approved YELLOW tools

Avoid another broad polish pass unless a new product screenshot or concrete UX gap exists.
