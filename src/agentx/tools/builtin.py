from __future__ import annotations

import ast
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from agentx.git_workflow import GitPushError, push_current_branch, stage_paths, unstage_paths
from agentx.memory_hall import MemoryHallClient
from agentx.protocol import Tool
from agentx.safety import Risk
from agentx.tools._helpers import (
    ALLOWED_COMMANDS,
    BUILD_COMMANDS,
    SKIPPED_DIRS,
    docker_compose_command,
    ensure_safe_write_path,
    extract_web_text,
    resolve_inside_workspace,
    run_subprocess,
    validate_external_url,
)


class _WorkspaceTool:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()


class ListFilesTool(_WorkspaceTool):
    name = "list_files"
    description = "列出 workspace 內檔案，會跳過 .git/.venv/cache 目錄"
    risk = Risk.GREEN
    signature = 'path=".", limit=200'

    def run(self, args: dict[str, Any]) -> str:
        path = args.get("path", ".")
        limit = int(args.get("limit", 200))
        root = resolve_inside_workspace(self.workspace, path)
        if not root.exists():
            raise FileNotFoundError(path)
        files: list[str] = []
        for item in sorted(root.rglob("*")):
            if any(part in SKIPPED_DIRS for part in item.relative_to(self.workspace).parts):
                continue
            if item.is_file():
                files.append(str(item.relative_to(self.workspace)))
            if len(files) >= limit:
                break
        return "\n".join(files)


class ReadFileTool(_WorkspaceTool):
    name = "read_file"
    description = "讀取 workspace 內指定檔案內容"
    risk = Risk.GREEN
    signature = "path, max_chars=20000"

    def run(self, args: dict[str, Any]) -> str:
        path = args["path"]
        max_chars = int(args.get("max_chars", 20000))
        target = resolve_inside_workspace(self.workspace, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text(encoding="utf-8", errors="replace")[:max_chars]


class WriteFileTool(_WorkspaceTool):
    name = "write_file"
    description = "寫入 workspace 內檔案（新檔或整檔重寫），自動建立父目錄；需 approval。改既有檔案的局部請改用 edit_file"
    risk = Risk.YELLOW
    signature = "path, content"

    def run(self, args: dict[str, Any]) -> str:
        path = args["path"]
        content = args.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        target = resolve_inside_workspace(self.workspace, path)
        if target == self.workspace:
            raise ValueError("path must not be the workspace root itself")
        ensure_safe_write_path(self.workspace, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        relative = target.relative_to(self.workspace)
        return f"wrote {len(content)} bytes to {relative}"


class EditFileTool(_WorkspaceTool):
    name = "edit_file"
    aliases = ["search_replace"]
    description = (
        "對 workspace 內既有檔案做 oldText→newText 替換；"
        "每個 oldText 必須在檔內出現恰好一次；改 bug／局部修正用這個比 write_file 安全"
    )
    risk = Risk.YELLOW
    signature = "path, edits=[{oldText, newText}]"

    def run(self, args: dict[str, Any]) -> str:
        path = args["path"]
        target = resolve_inside_workspace(self.workspace, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        ensure_safe_write_path(self.workspace, target)

        edits = _coerce_edits(args)
        if not edits:
            raise ValueError("edits must contain at least one {oldText, newText} entry")

        content = target.read_text(encoding="utf-8", errors="replace")
        for index, edit in enumerate(edits):
            old_text = str(edit.get("oldText", ""))
            new_text = str(edit.get("newText", ""))
            if not old_text:
                raise ValueError(f"edits[{index}].oldText must not be empty")
            count = content.count(old_text)
            if count == 0:
                raise ValueError(
                    f"edits[{index}] 找不到指定的 oldText 在 {path}。"
                    " oldText 必須完整符合，包含所有空白與換行。"
                )
            if count > 1:
                raise ValueError(
                    f"edits[{index}] 在 {path} 找到 {count} 處 oldText 出現；"
                    " 每個 oldText 必須唯一，請加上更多前後文以區分。"
                )
            content = content.replace(old_text, new_text, 1)

        target.write_text(content, encoding="utf-8")
        return f"applied {len(edits)} edit(s) to {target.relative_to(self.workspace)}"


class InsertCodeTool(_WorkspaceTool):
    """Precise insert for writing code. Insert new content immediately after a unique marker string.
    Promoted heavily in prompts for small, safe additions (e.g. add a function after a marker line).
    Must appear exactly once (like edit_file's oldText rule) to prevent accidental wrong inserts.
    """
    name = "insert_code"
    description = (
        "在 workspace 既有檔案的指定 marker 之後插入內容；"
        "marker 必須在檔內出現恰好一次；適合新增函式、區塊等精準寫入"
    )
    risk = Risk.YELLOW
    signature = 'path, insert_after="marker line or string", content="new code to insert"'

    def run(self, args: dict[str, Any]) -> str:
        path = args["path"]
        target = resolve_inside_workspace(self.workspace, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        ensure_safe_write_path(self.workspace, target)

        marker = str(args.get("insert_after", ""))
        to_insert = str(args.get("content", ""))
        if not marker:
            raise ValueError("insert_after (marker) must not be empty")
        if not isinstance(to_insert, str):
            to_insert = str(to_insert)

        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(marker)
        if count == 0:
            raise ValueError(
                f"insert_after marker not found in {path}. "
                "The marker string must appear exactly as provided."
            )
        if count > 1:
            raise ValueError(
                f"insert_after marker appears {count} times in {path}; "
                "each marker must be unique — include more surrounding context."
            )

        idx = content.find(marker)
        insert_pos = idx + len(marker)
        new_content = content[:insert_pos] + to_insert + content[insert_pos:]
        target.write_text(new_content, encoding="utf-8")

        # Report relative path and size for clarity in transcripts / learning
        rel = target.relative_to(self.workspace)
        return f"inserted {len(to_insert)} bytes after marker in {rel}"


def _coerce_edits(args: dict[str, Any]) -> list[dict[str, Any]]:
    edits = args.get("edits")
    if isinstance(edits, list):
        cleaned: list[dict[str, Any]] = []
        for index, entry in enumerate(edits):
            if not isinstance(entry, dict):
                # Review N9: surface malformed entries instead of silently
                # dropping them — partial intent should not be reported as ok.
                raise ValueError(
                    f"edits[{index}] must be a dict with oldText/newText, "
                    f"got {type(entry).__name__}"
                )
            cleaned.append(entry)
        return cleaned
    old_text = args.get("oldText") or args.get("old_string") or args.get("old_text")
    new_text = args.get("newText") or args.get("new_string") or args.get("new_text")
    if isinstance(old_text, str) and isinstance(new_text, str):
        return [{"oldText": old_text, "newText": new_text}]
    return []


class SearchTextTool(_WorkspaceTool):
    name = "search_text"
    description = "使用 rg 搜尋 workspace 內文字"
    risk = Risk.GREEN
    signature = 'pattern, path=".", limit=100'

    def run(self, args: dict[str, Any]) -> str:
        pattern = args["pattern"]
        path = args.get("path", ".")
        limit = int(args.get("limit", 100))
        root = resolve_inside_workspace(self.workspace, path)
        _, output = run_subprocess(
            ["rg", "--line-number", "--color", "never", pattern, str(root)],
            cwd=self.workspace,
        )
        return "\n".join(output.splitlines()[:limit])


class FindFilesTool(_WorkspaceTool):
    name = "find_files"
    description = "依 keyword 同時搜尋 workspace 檔名/路徑與內容，輸出分組結果與 /read 建議"
    risk = Risk.GREEN
    signature = 'keyword, path=".", path_limit=20, content_limit=50, read_limit=5'

    def run(self, args: dict[str, Any]) -> str:
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            raise ValueError("keyword is required")

        path = args.get("path", ".")
        path_limit = max(1, min(int(args.get("path_limit", 20)), 100))
        content_limit = max(1, min(int(args.get("content_limit", 50)), 200))
        read_limit = max(1, min(int(args.get("read_limit", 5)), 20))
        root = resolve_inside_workspace(self.workspace, path)
        if not root.exists():
            raise FileNotFoundError(path)

        path_matches = self._path_matches(root, keyword, path_limit)
        content_matches = self._content_matches(root, keyword, content_limit)
        read_suggestions = self._read_suggestions(path_matches, content_matches, read_limit)

        if not path_matches and not content_matches:
            return f"No matches for {keyword!r} under {Path(path).as_posix() or '.'}."

        sections: list[str] = []
        sections.append("## Path matches")
        sections.extend(f"- {match}" for match in path_matches)
        if not path_matches:
            sections.append("- (none)")

        sections.append("## Content matches")
        sections.extend(f"- {match}" for match in content_matches)
        if not content_matches:
            sections.append("- (none)")

        sections.append("## Suggested /read")
        sections.extend(f"- /read {match}" for match in read_suggestions)
        if not read_suggestions:
            sections.append("- (none)")

        return "\n".join(sections)

    def _path_matches(self, root: Path, keyword: str, limit: int) -> list[str]:
        needle = keyword.casefold()
        matches: list[str] = []
        for item in sorted(root.rglob("*")):
            try:
                relative = item.relative_to(self.workspace)
            except ValueError:
                continue
            if any(part in SKIPPED_DIRS for part in relative.parts):
                continue
            if not item.is_file():
                continue
            relative_text = relative.as_posix()
            if needle in relative_text.casefold():
                matches.append(relative_text)
            if len(matches) >= limit:
                break
        return matches

    def _content_matches(self, root: Path, keyword: str, limit: int) -> list[str]:
        cmd = [
            "rg",
            "--line-number",
            "--color",
            "never",
            "--fixed-strings",
            "--ignore-case",
        ]
        for skipped in sorted(SKIPPED_DIRS):
            cmd.extend(["--glob", f"!{skipped}/**"])
        search_path = "." if root == self.workspace else root.relative_to(self.workspace).as_posix()
        cmd.extend([keyword, search_path])
        _, output = run_subprocess(cmd, cwd=self.workspace)
        lines: list[str] = []
        for line in output.splitlines():
            if line.startswith("./"):
                line = line[2:]
            if line:
                lines.append(line)
            if len(lines) >= limit:
                break
        return lines

    @staticmethod
    def _read_suggestions(
        path_matches: list[str],
        content_matches: list[str],
        limit: int,
    ) -> list[str]:
        suggestions: list[str] = []

        def add(path: str) -> None:
            if path and path not in suggestions:
                suggestions.append(path)

        for path in path_matches:
            add(path)
            if len(suggestions) >= limit:
                return suggestions

        for line in content_matches:
            path = line.split(":", 1)[0]
            add(path)
            if len(suggestions) >= limit:
                return suggestions

        return suggestions


class GitStatusTool(_WorkspaceTool):
    name = "git_status"
    description = "查看 git status --short --branch"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        _, output = run_subprocess(["git", "status", "--short", "--branch"], cwd=self.workspace)
        return output


class GitBranchTool(_WorkspaceTool):
    name = "git_branch"
    description = "查看本地 git branch（唯讀）"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        _ = args
        _, output = run_subprocess(["git", "branch", "--no-color"], cwd=self.workspace)
        return output


class GitLogTool(_WorkspaceTool):
    name = "git_log"
    description = "查看最近 git log（唯讀，限制筆數）"
    risk = Risk.GREEN
    signature = "limit=10"

    def run(self, args: dict[str, Any]) -> str:
        limit = max(1, min(int(args.get("limit", 10)), 50))
        _, output = run_subprocess(
            ["git", "log", "--oneline", "--decorate", f"-n{limit}"],
            cwd=self.workspace,
        )
        return output


class GitShowTool(_WorkspaceTool):
    name = "git_show"
    description = "查看單一 git revision（唯讀，拒絕 flags/options）"
    risk = Risk.GREEN
    signature = 'rev="HEAD", max_chars=30000'

    def run(self, args: dict[str, Any]) -> str:
        rev = str(args.get("rev", "HEAD") or "HEAD").strip()
        if not rev:
            rev = "HEAD"
        if rev.startswith("-") or any(token in rev for token in (" ", "\t", "\n", "\r")):
            raise ValueError(f"unsupported git revision: {rev!r}")
        max_chars = int(args.get("max_chars", 30000))
        _, output = run_subprocess(["git", "show", "--stat", "--oneline", "--no-color", rev], cwd=self.workspace)
        return output[:max_chars]


class GitDiffTool(_WorkspaceTool):
    name = "git_diff"
    description = "查看 git diff，可指定單一 path"
    risk = Risk.GREEN
    signature = "path=null, max_chars=30000"

    def run(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        max_chars = int(args.get("max_chars", 30000))
        cmd = ["git", "diff"]
        if path:
            resolve_inside_workspace(self.workspace, path)
            cmd.extend(["--", path])
        _, output = run_subprocess(cmd, cwd=self.workspace)
        return output[:max_chars]


class GitStageTool(_WorkspaceTool):
    name = "git_stage"
    description = "逐檔 git add 指定 path；拒絕 .、glob、目錄與 workspace 外路徑"
    risk = Risk.YELLOW
    signature = "paths=[path, ...]"

    def run(self, args: dict[str, Any]) -> str:
        return stage_paths(self.workspace, _coerce_git_paths(args))


class GitUnstageTool(_WorkspaceTool):
    name = "git_unstage"
    description = "逐檔 git restore --staged 指定 path；保留 worktree 修改"
    risk = Risk.YELLOW
    signature = "paths=[path, ...]"

    def run(self, args: dict[str, Any]) -> str:
        return unstage_paths(self.workspace, _coerce_git_paths(args))


class GitPushTool(_WorkspaceTool):
    name = "git_push"
    description = "推送目前 branch 到既有 upstream；不接受 refspec、force 或 -u"
    risk = Risk.YELLOW
    signature = ""

    def run(self, args: dict[str, Any]) -> str:
        if args:
            raise ValueError("git_push does not accept arguments")
        output = push_current_branch(self.workspace)
        if "push aborted:" in output:
            raise GitPushError(output)
        return output


def _coerce_git_paths(args: dict[str, Any]) -> list[str]:
    paths = args.get("paths")
    if isinstance(paths, list):
        return [str(path) for path in paths]
    path = args.get("path")
    if path is None:
        return []
    return [str(path)]


class MemorySearchTool:
    name = "memory_search"
    description = "查詢 Memory Hall（支援 ACA namespace 與 tier 標記的記憶）"
    risk = Risk.GREEN
    signature = 'query, namespace="shared", limit=5'

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        return self.memory.search(
            query=args["query"],
            namespace=args.get("namespace", "shared"),
            limit=int(args.get("limit", 5)),
        )


class MemoryWriteTool:
    name = "memory_write"
    description = (
        "寫入 Memory Hall。ACA 相容：建議傳 tier=llm_derived|human_confirmed|raw_source 與 "
        "memory_type=lesson|decision|fact|...  以符合 Agent Civilization Architecture 治理規則 "
        "（Anti-Ouroboros：llm_derived 不得無人為介入就 supersede 另一個 llm_derived）。"
    )
    risk = Risk.YELLOW
    signature = 'content, namespace="agent:agentx", tier="llm_derived", memory_type="note"'

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        tier = args.get("tier")
        memory_type = args.get("memory_type") or args.get("type")

        if tier or memory_type:
            # Explicit ACA request → must use write_aca, fail closed on error (Codex Medium)
            resp = self.memory.write_aca(
                content=args["content"],
                namespace=args.get("namespace", "agent:agentx"),
                source_tier=tier or "llm_derived",
                memory_type=memory_type or "note",
            )
            return f"aca_write ok (tier={tier or 'llm_derived'}) entry_id={resp.get('entry_id', 'n/a')}"

        # Pure legacy path (no tier/memory_type requested)
        return self.memory.write(
            content=args["content"],
            namespace=args.get("namespace", "agent:agentx"),
        )


class MemoryTierUpgradeTool:
    name = "memory_tier_upgrade"
    description = (
        "ACA L2 Trust 操作：將一筆記憶的 source tier 升級（通常 llm_derived → human_confirmed）。"
        "需提供 memory_id、confirmed_by（人類 principal）、可選 evidence_ids。會寫入 TrustProof 紀錄。"
    )
    risk = Risk.YELLOW
    signature = 'memory_id, new_tier="human_confirmed", confirmed_by, method="human_review", evidence_ids=[], namespace="project:agentX"'

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        self.memory.tier_upgrade(
            args["memory_id"],
            new_tier=args.get("new_tier", "human_confirmed"),
            confirmed_by=args["confirmed_by"],
            method=args.get("method", "human_review"),
            evidence_ids=args.get("evidence_ids") or [],
            namespace=args.get("namespace"),
        )
        return f"tier_upgrade ok for {args['memory_id']} -> {args.get('new_tier', 'human_confirmed')}"


class MemoryAuditTool:
    name = "memory_audit"
    description = "ACA L1/L2：讀取某筆記憶的 append-only 事件紀錄（寫入、tier 變更、轉移等）。"
    risk = Risk.GREEN
    signature = 'memory_id'

    def __init__(self, memory: MemoryHallClient) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> str:
        events = self.memory.audit(args["memory_id"])
        if not events:
            return f"no audit events found for {args['memory_id']}"
        lines = [f"- {e.get('event', 'unknown')}: {str(e.get('data', ''))[:200]}" for e in events[:10]]
        return "\n".join(lines)


class RunCommandTool(_WorkspaceTool):
    name = "run_command"
    description = "執行 GREEN allowlist 命令（read-only 檢查、純語法掃描）"
    risk = Risk.GREEN
    signature = "command"

    def run(self, args: dict[str, Any]) -> str:
        command = args["command"]
        if command not in ALLOWED_COMMANDS:
            allowed = "\n".join(f"- {item}" for item in sorted(ALLOWED_COMMANDS))
            raise PermissionError(f"Command is not allowlisted: {command}\nAllowed:\n{allowed}")
        completed = subprocess.run(
            ALLOWED_COMMANDS[command],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        output = completed.stdout or completed.stderr
        return f"$ {command}\nexit={completed.returncode}\n{output.strip()}"


class RunBuildCommandTool(_WorkspaceTool):
    name = "run_build_command"
    description = (
        "執行 YELLOW build/test allowlist 命令（cargo check/build/test/clippy）；"
        "會 invoke build.rs、proc-macro、測試碼 = 執行任意 repo 內程式，故需 approval"
    )
    risk = Risk.YELLOW
    signature = "command"

    def run(self, args: dict[str, Any]) -> str:
        command = args["command"]
        if command not in BUILD_COMMANDS:
            allowed = "\n".join(f"- {item}" for item in sorted(BUILD_COMMANDS))
            raise PermissionError(f"Command is not allowlisted: {command}\nAllowed:\n{allowed}")
        completed = subprocess.run(
            BUILD_COMMANDS[command],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        output = completed.stdout or completed.stderr
        return f"$ {command}\nexit={completed.returncode}\n{output.strip()}"


class RunTestsTool(_WorkspaceTool):
    name = "run_tests"
    description = "執行固定 allowlist 驗證：ruff check 與 pytest"
    risk = Risk.GREEN

    def run(self, args: dict[str, Any]) -> str:
        commands = [
            ["uv", "run", "ruff", "check", "."],
            ["uv", "run", "pytest", "-q"],
        ]
        outputs: list[str] = []
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            output = completed.stdout or completed.stderr
            outputs.append(
                f"$ {' '.join(command)}\nexit={completed.returncode}\n{output.strip()}"
            )
            if completed.returncode != 0:
                break
        return "\n\n".join(outputs)


class ApplyPatchTool(_WorkspaceTool):
    name = "apply_patch"
    description = "套用 unified diff patch，需 approval"
    risk = Risk.YELLOW
    signature = "patch"

    def run(self, args: dict[str, Any]) -> str:
        patch = args["patch"]
        # Use system temp file for patch content. Never write untrusted patch data
        # into the workspace (including .agentx/patches). This hardens the staging
        # surface compared to writing pending.patch under protected .agentx dir.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(patch)
            patch_path = Path(tf.name)

        try:
            check = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if check.returncode != 0:
                return f"git apply --check failed\n{check.stdout}{check.stderr}".strip()

            # Collect touched paths from two sources (defense in depth):
            # 1. String parse of the raw patch text (catches declared intent early)
            # 2. git apply --name-only (uses git's own robust parser for quoting,
            #    spaces, " b/" in names, renames, copies, binary patches, etc.)
            paths: set[str] = _patch_write_paths(patch)

            name_only = subprocess.run(
                ["git", "apply", "--name-only", str(patch_path)],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if name_only.returncode == 0:
                for line in name_only.stdout.strip().splitlines():
                    p = line.strip()
                    if p and p != "/dev/null":
                        paths.add(p)

            for path in paths:
                ensure_safe_write_path(
                    self.workspace, resolve_inside_workspace(self.workspace, path)
                )

            applied = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            output = (applied.stdout + applied.stderr).strip()
            if applied.returncode != 0:
                return f"git apply failed\n{output}".strip()
            return output or "patch applied"
        finally:
            try:
                patch_path.unlink(missing_ok=True)
            except Exception:
                pass


def _patch_write_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            old, _, new = line.removeprefix("diff --git ").rpartition(" b/")
            _add_patch_path(paths, old, strip=1)
            if new:
                _add_patch_path(paths, f"b/{new}", strip=1)
            continue
        if line.startswith(("--- ", "+++ ")):
            _add_patch_path(paths, line[4:], strip=1)
        elif line.startswith(("rename from ", "rename to ")):
            _add_patch_path(paths, line.removeprefix("rename from ").removeprefix("rename to "), strip=0)
        elif line.startswith(("copy from ", "copy to ")):
            _add_patch_path(paths, line.removeprefix("copy from ").removeprefix("copy to "), strip=0)
    return paths


def _add_patch_path(paths: set[str], raw: str, *, strip: int) -> None:
    path = _patch_path(raw, strip=strip)
    if path and path != "/dev/null":
        paths.add(path)


def _patch_path(raw: str, *, strip: int) -> str | None:
    token = raw.split("\t", 1)[0].strip()
    if token.startswith('"'):
        token = ast.literal_eval(token)
    if token == "/dev/null":
        return token
    parts = token.split("/")
    if len(parts) <= strip:
        return None
    return "/".join(parts[strip:])


class _DockerComposeTool(_WorkspaceTool):
    action: str = ""

    def _run_action(self, args: dict[str, Any]) -> str:
        command = docker_compose_command(
            self.workspace,
            self.action,
            compose_file=args.get("compose_file"),
            service=args.get("service"),
            tail=int(args.get("tail", 100)),
        )
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        output = completed.stdout or completed.stderr
        return f"$ {' '.join(command)}\nexit={completed.returncode}\n{output.strip()}"


class DockerComposePsTool(_DockerComposeTool):
    name = "docker_compose_ps"
    description = "查看 docker compose ps"
    risk = Risk.GREEN
    signature = "compose_file=null"
    action = "ps"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeBuildTool(_DockerComposeTool):
    name = "docker_compose_build"
    description = "執行 docker compose build，需 approval"
    risk = Risk.YELLOW
    signature = "compose_file=null"
    action = "build"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeUpTool(_DockerComposeTool):
    name = "docker_compose_up"
    description = "執行 docker compose up -d，需 approval"
    risk = Risk.YELLOW
    signature = "compose_file=null"
    action = "up"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeDownTool(_DockerComposeTool):
    name = "docker_compose_down"
    description = "執行 docker compose down，需 approval"
    risk = Risk.YELLOW
    signature = "compose_file=null"
    action = "down"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


class DockerComposeLogsTool(_DockerComposeTool):
    name = "docker_compose_logs"
    description = "查看 docker compose logs"
    risk = Risk.GREEN
    signature = "compose_file=null, service=null, tail=100"
    action = "logs"

    def run(self, args: dict[str, Any]) -> str:
        return self._run_action(args)


# Bounded defaults for external HTTP fetches (SSRF-hardened, read-only).
_WEB_FETCH_DEFAULT_TIMEOUT = 10.0
_WEB_FETCH_MAX_TIMEOUT = 60.0
_WEB_FETCH_DEFAULT_MAX_CHARS = 20_000
_WEB_FETCH_MAX_CHARS = 100_000
_WEB_FETCH_DEFAULT_MAX_BYTES = 2_000_000
_WEB_FETCH_MAX_BYTES = 5_000_000
_WEB_FETCH_TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/x-javascript",
)


class WebFetchTool:
    """GREEN read-only fetch of a single external URL, cleaned to plain text."""

    name = "web_fetch"
    description = (
        "讀取指定外部 URL 的文字內容（僅 http/https 公網；"
        "會阻擋 localhost/private IP；HTML 會清理成純文字）"
    )
    risk = Risk.GREEN
    signature = "url, max_chars=20000, timeout=10, max_bytes=2000000"

    def run(self, args: dict[str, Any]) -> str:
        url = args["url"]
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url is required")

        max_chars = int(args.get("max_chars", _WEB_FETCH_DEFAULT_MAX_CHARS))
        max_chars = max(1, min(max_chars, _WEB_FETCH_MAX_CHARS))
        timeout = float(args.get("timeout", _WEB_FETCH_DEFAULT_TIMEOUT))
        timeout = max(1.0, min(timeout, _WEB_FETCH_MAX_TIMEOUT))
        max_bytes = int(args.get("max_bytes", _WEB_FETCH_DEFAULT_MAX_BYTES))
        max_bytes = max(1, min(max_bytes, _WEB_FETCH_MAX_BYTES))

        # SSRF gate: must run before any network I/O.
        validate_external_url(url)

        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                normalized_type = content_type.split(";", 1)[0].strip().lower()
                if normalized_type and not normalized_type.startswith(_WEB_FETCH_TEXT_CONTENT_TYPES):
                    raise ValueError(f"unsupported content-type: {content_type}")
                encoding = getattr(response, "encoding", None) or "utf-8"

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"response too large: exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                body = b"".join(chunks)

            text = body.decode(encoding, errors="replace")
            text = extract_web_text(text, content_type)
            return text[:max_chars]


def builtin_tools(workspace: Path, memory: MemoryHallClient) -> list[Tool]:
    return [
        ListFilesTool(workspace),
        ReadFileTool(workspace),
        WriteFileTool(workspace),
        EditFileTool(workspace),
        InsertCodeTool(workspace),
        SearchTextTool(workspace),
        FindFilesTool(workspace),
        GitStatusTool(workspace),
        GitBranchTool(workspace),
        GitLogTool(workspace),
        GitShowTool(workspace),
        GitDiffTool(workspace),
        GitStageTool(workspace),
        GitUnstageTool(workspace),
        GitPushTool(workspace),
        MemorySearchTool(memory),
        MemoryWriteTool(memory),
        MemoryTierUpgradeTool(memory),
        MemoryAuditTool(memory),
        RunCommandTool(workspace),
        RunBuildCommandTool(workspace),
        RunTestsTool(workspace),
        ApplyPatchTool(workspace),
        WebFetchTool(),
        DockerComposePsTool(workspace),
        DockerComposeBuildTool(workspace),
        DockerComposeUpTool(workspace),
        DockerComposeDownTool(workspace),
        DockerComposeLogsTool(workspace),
    ]
