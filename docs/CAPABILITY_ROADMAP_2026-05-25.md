# agentX Capability Roadmap — Git, Local Search, Intent Understanding

**Date**: 2026-05-25  
**Decision**: Proceed, but build in the order that improves execution reliability first.

Maki's requested next focus areas:

1. Git operation capability
2. Local file retrieval by keyword
3. More advanced understanding of user intent

Engineering recommendation: do these, but start with local file retrieval, then Git, then intent understanding. Search and Git are the agent's hands; intent understanding is only useful when it can reliably inspect and change the workspace.

## Current Baseline

agentX already has:

- `/files`, `/read`, `/search`, `/attach`
- `/git`, `/diff`, `/review`, `/commit`
- `/task`, `/guide`, `/workflows`, `/handoff`, `/resume`
- safety classification and approval aliases

The next phase should make these capabilities more complete and easier to use from natural user requests.

## P0: Local File Retrieval

Goal: make agentX quickly find relevant files by keyword, path, and topic before editing.

Current status:

- [x] `/find KEYWORD` implemented as a deterministic GREEN tool/slash command:
  filename/path substring matches + fixed-string content matches + capped `/read` suggestions.
- [x] `/grep KEYWORD [PATH]` implemented as a thin slash wrapper over `search_text(pattern, path)`.
- [x] `/where TOPIC` implemented as deterministic topic cleanup + ranked likely locations; no model-only guessing.

Proposed commands:

- `/find KEYWORD`
  - Search filenames, paths, and content.
  - Return grouped results: path matches, content matches, likely entry points.
  - Include line numbers, snippets, and suggested `/read PATH`.
- `/grep KEYWORD [PATH]`
  - Explicit content search, closer to `rg`.
  - Useful for precise engineering work.
- `/where TOPIC`
  - Natural-language-ish lookup for "where is approval policy" or "where is handoff built".
  - Deterministic first: keyword expansion plus existing repo structure, not a model-only guess.

Acceptance:

- Tests cover filename match, content match, scoped path search, no-result output, and snippet formatting.
- Output does not overwhelm narrow terminals.
- Existing `/search` remains compatible.

## P1: Git Operation Loop

Goal: let agentX complete a safe Git unit without relying on raw shell commands.

Proposed commands:

- [x] `/git status`
- [x] `/git branch`
- [x] `/git log [N]`
- [x] `/git show [REV]`
- [x] `/stage PATH...` (explicit files only; rejects broad paths, glob, directories, workspace escape)
- [x] `/unstage PATH...` (explicit files only; preserves worktree changes)
- [x] `/push` (current branch only; requires existing upstream; no args, force, refspec, or auto `-u`)

Keep `/commit [MESSAGE]`, but make the flow clearer:

- show `git status`
- show `git diff --stat`
- stage only explicit files
- run tests
- commit with Chinese message
- push

Safety:

- Keep `git add .` out of the default flow.
- Reject or RED-gate `push --force`, `reset --hard`, `clean`, destructive checkout/restore, and broad path operations.
- Transcript should record staged files, commit hash, push target, and test result.

Acceptance:

- Unit tests cover staging single files, rejecting broad stage, unstage, push command construction, and force-push rejection.
- Existing `/commit` tests continue to pass.
- No change to RED destructive behavior without explicit approval.

## P2: Intent Understanding

Goal: help users turn vague requests into a concrete, verifiable task plan without making the shell chatty or blocking.

Proposed commands:

- `/intent TEXT`
  - Output: interpreted goal, constraints, risk, files to inspect, verification plan.
- `/plan-task TEXT`
  - Convert a user request into `/task` checklist entries.

Runtime behavior:

- For complex natural-language requests, agentX can first produce a compact execution brief:
  - understood goal
  - planned inspection targets
  - risk flags
  - verification command
- Ask a question only when needed: production impact, deletion, cross-repo ambiguity, missing target, or contradictory instructions.

Acceptance:

- Tests cover simple request, ambiguous request, high-risk request, and conversion to task checklist.
- The feature improves execution, not just explanation quality.
- No automatic production, destructive, or remote action is triggered by intent classification.

## Recommended Commit Order

1. `強化本地檔案檢索`
   - Implement `/find` and improve `/search` output.
   - Add focused tests.
2. `補齊 git 操作閉環`
   - Add stage/unstage/push and safer git subcommands.
   - Strengthen `/commit` transcript and tests.
3. `新增需求理解與任務拆解`
   - Add `/intent` or `/plan-task`.
   - Keep behavior deterministic first.

## Non-Goals

- Do not add broad arbitrary shell execution.
- Do not loosen RED protections.
- Do not make a model call mandatory for every command.
- Do not implement a large planner before search and Git are reliable.
