# AGENTX.md — agentX Project Rules, Architecture & Self-Improvement Guide

**Purpose**: This is the canonical, living instruction file for the agentX project itself.  
When running `ax` (or `agentx`) inside this repository, agentX MUST treat the content of this file as high-priority context and rules.

**Last major update**: 2026-06 (post MT22 merge + initial self-instruction setup)

---

## Self-Improvement & Modification Protocol (CRITICAL)

This file exists so that agentX can **learn and improve itself**.

**You are explicitly authorized to:**
- Read this file at any time (use `read_file` on `AGENTX.md`).
- Learn from it: internalize principles, avoid past mistakes, follow current best practices.
- Modify it: when you discover better ways of working, complete major features, resolve architectural debt, or identify new rules, **you should propose and apply updates** using `edit_file`, `write_file`, or search-replace tools.

**Modification Rules**:
1. Always use precise edits. Prefer small, reviewable changes.
2. After significant edits, run relevant tests (`uv run pytest ...`) and `uv run ruff check`.
3. Document the reason for the change (e.g., "Learned from MT22 headless work that...").
4. Update the "Last major update" date at the top.
5. If a rule is being deprecated, keep a short historical note + the new preferred approach.
6. Never delete this file or its core purpose.
7. When you modify AGENTX.md, consider also updating related docs (e.g. `docs/MT22-Migration-Guide.md`, `OPTIMIZATION_ROADMAP.md`) for human readers.
8. After self-modification, it is good practice to run `agentx doctor` and review the current state.

This protocol makes agentX a self-improving system inside its own codebase.

---

## Core Principles

1. **Risk-First & Safety Always**
   - Every tool has a clear risk level: GREEN (auto), YELLOW (policy), RED (protected).
   - Default to `approval = "ask"` mode unless user explicitly sets otherwise.
   - Never bypass approval mechanisms without explicit user intent.

2. **Multi-Task System is the Single Source of Truth (MT22)**
   - `.agentx/tasks.json` + `agentx.tasks` API is the only authoritative task state.
   - The old single-task system (`task.py`, `.agentx/task.json`) has been fully removed.
   - All new code, tools, prompts, and CLI must use the multi-task list.
   - Legacy migration happens automatically on startup when old `task.json` is detected (backup created).

3. **Headless Mode is a First-Class Citizen**
   - Headless (`-p --agent`) requires different behavior from interactive TUI: more decisive, less reflection loops, structured output.
   - Long-running headless tasks must survive context loss via proper compaction, task lists, and Memory Hall.
   - Plan Mode (`--plan`) must force at least one high-quality reflection before tool use in headless.

4. **Memory Hall is Core Infrastructure**
   - Persistent cross-session memory via Memory Hall is not optional.
   - Use structured writes when possible (`write_structured` for lessons, patterns, decisions).
   - Initial context always includes repo bootstrap + memory search.

5. **Small Steps + Complete Verification + Chinese Commits**
   - Prefer many small, reviewable commits over large ones.
   - Every logical unit of work should include tests or verification.
   - Commit messages are in Chinese (following project convention).
   - Run `ruff check` and relevant tests before committing.

6. **Weak Models Can Be Reliable**
   - The goal is not to make weak models "smart" in a black-box way, but to give them strong scaffolding (tools, memory, recovery, task lists, reflection protocols) so they can reliably complete real engineering work within safe boundaries.

---

## Architecture & State Management

- **Workspace**: The directory where `ax` is invoked becomes the workspace. All file tools are sandboxed to it.
- **Persistent State**: Stored under `.agentx/` (not committed to git):
  - `config.toml` — per-project settings (model, namespace, approval mode, etc.)
  - `tasks.json` — the multi-task source of truth.
  - `sessions/` — session logs.
  - `handoff/` — conversation handoff notes (local, not in git).
  - `state.json` — lightweight runtime state.
- **Bootstrap Context**: On every significant operation, agentX reads `AGENTX.md` (preferred), `AGENTS.md`, `README.md`, `pyproject.toml`, and `package.json` from the workspace root to understand the project.

**Never**:
- Write directly to `.agentx/task.json` (legacy).
- Assume a single active task.
- Bypass the workspace sandbox.

---

## Key Conventions & Current State (as of 2026-06)

### MT22 Legacy Removal (Completed)
- `src/agentx/task.py` has been removed.
- All task management now goes through `agentx.tasks` (multi-task list).
- Legacy migration is automatic and one-way.
- Doctor command can still diagnose remaining legacy data for safety.
- Tests for legacy are marked as historical only.

See `docs/MT22-Migration-Guide.md` and `docs/MT22-Legacy-Removal-Checklist.md` for details.

### Headless & Reliability Focus
- Primary development target: making headless mode reliable for medium-to-large engineering tasks.
- Key areas: context compaction, error recovery, structured reflection, task list integration, prompt separation between interactive and headless.
- Current roadmap lives in `docs/OPTIMIZATION_ROADMAP.md` and `docs/HEADLESS_OPTIMIZATION_LIST.md`.

### Tooling & Safety
- Tools are defined in `src/agentx/tools/builtin.py` and registered via `ToolRegistry`.
- New tools should be added to `builtin_tools(workspace, memory)`.
- Web-related helpers (`extract_web_text`, `validate_external_url`) exist for future web_fetch support.
- Always respect `WRITE_PROTECTED_PARTS` and `SKIPPED_DIRS`.

### Prompts & Behavior
- Different system prompts for interactive vs headless (see `runtime_prompt.py`).
- Headless emphasizes decisiveness and structured output.
- Weak models benefit from explicit verification steps after edits.

---

## Development Workflow When Working on agentX

1. Start with `ax` or `agentx ask` inside this repo.
2. Read `AGENTX.md` early (and relevant docs in `docs/`).
3. Use the multi-task list (`/task` or task tools) for any non-trivial work.
4. Make small, testable changes.
5. Run `uv run ruff check` and targeted tests frequently.
6. Use Memory Hall to record lessons (especially success patterns and failure modes).
7. Chinese commit messages.
8. When you learn something important, **update AGENTX.md**.
9. For large changes, consider adding/updating entries in the relevant optimization list or migration guide.

---

## Self-Modification Rules (Reinforced)

- You have full permission to edit `AGENTX.md`.
- Treat updates to this file as first-class deliverables.
- When editing:
  - Be precise.
  - Add new rules or lessons in appropriate sections.
  - Mark completed items in roadmaps/checklists (or link to them).
  - If a practice changes, document both the old and new approach with rationale.
- After editing AGENTX.md, it is recommended to run `agentx doctor` and verify that the agent can still parse its own instructions correctly.

This file is how agentX teaches future versions of itself.

---

## References (Read These When in Doubt)

- `README.md` — high-level product description and quick start.
- `docs/MT22-Migration-Guide.md` — current canonical rules around tasks.
- `docs/OPTIMIZATION_ROADMAP.md` — overall direction and priorities.
- `docs/HEADLESS_OPTIMIZATION_LIST.md` — detailed headless improvement backlog.
- `docs/product-tour.md` — vision and feature mapping.
- `.agentx/config.toml` — current runtime configuration for this instance.
- `src/agentx/bootstrap.py` — how workspace context (including this file) is loaded.

---

## Current Model & Environment Notes (2026-06)

- Default model for this project instance: gemma4 series (local Ollama).
- Strong preference for local models with good tool-calling + JSON reliability.
- Memory Hall is assumed available (mini or equivalent).
- The project itself is the primary testbed for headless reliability.

---

**End of AGENTX.md**

This file should be the first thing an agentX instance reads when working inside the agentX repository.
