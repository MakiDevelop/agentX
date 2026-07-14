from __future__ import annotations

import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.columns import Columns
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agentx import cli_runtime_handlers as _runtime_handlers
from agentx import cli_slash_shims as _slash_shims
from agentx.approval import ApprovalMode, ApprovalPolicy, approval_decision_source, normalize_approval_mode
from agentx.attachments import extract_file_paths, format_attachment_context, read_attachments
from agentx.config import Settings
from agentx.command_catalog import (
    COMMAND_CATALOG,
    SLASH_COMMANDS,
    capabilities_payload,
    command_catalog_payload,
    filtered_command_catalog_payload,
    format_unknown_slash_command,
    normalize_slash_command_topic,
    slash_command_help,
    slash_command_suggestions,
)
from agentx.context_compactor import LLMContextCompactor
from agentx.doctor import run_doctor, run_static_doctor
from agentx.git_workflow import build_commit_plan, commit_and_push
from agentx.infrastructure_context import build_infrastructure_context, infrastructure_context_metadata
from agentx.intent import plan_task_items
from agentx.jobs import PromptJobQueue
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient, NullMemoryClient
from agentx.ollama import OllamaCancelledError, OllamaClient
from agentx.provider_registry import get_llm_client, list_registered_backends, LLMClient, register_builtin_backends
from agentx.persona import list_personas, normalize_persona
from agentx.project_config import load_project_config, set_project_config
from agentx.project_profile import build_project_profile, build_project_profile_payload
from agentx.project_state import mark_guide_hint_seen, should_show_guide_hint
from agentx.prompting import SlashCommandCompleter
from agentx.runtime_prompt import build_chat_system_prompt, build_headless_agent_system_prompt
from agentx.safety import Risk
from agentx.tasks import (
    format_task_list_summary,
    get_next_task_id,
    load_tasks,
    migrate_single_task_if_needed,
    save_tasks,
)
from agentx.tools import (
    ALLOWED_COMMANDS,
    BUILD_COMMANDS,
    DOCKER_COMPOSE_ACTIONS,
    ToolRegistry,
    builtin_tools,
    docker_compose_command,
    ensure_safe_write_path,
    patch_write_paths,
    resolve_inside_workspace,
    tool_aliases,
    tool_is_enabled,
    tool_signature,
)
from agentx.transcript import (
    Transcript,
    approval_receipts,
    find_transcript,
    format_approval_receipts,
    list_transcripts,
    resume_loaded_message,
    summarize_transcript,
    transcript_overview,
)
from agentx.tui import AgentXTui, format_assistant_header

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentx.config import Settings
    from agentx.loop import AgentSession


HEADLESS_PAYLOAD_SCHEMA_VERSION = "agentx.headless_result.v1"




@dataclass
class ShellState:
    """管理互動式 shell 的狀態（階段一基礎版）"""
    settings: "Settings"
    agent_session: "AgentSession | None" = None
    memory: "MemoryHallClient | None" = None  # for hot-reload of ACA amh backend
    plan_mode: bool = False
    mode: str = "chat"           # "chat" 或 "agent"
    namespace: str = "project:agentX"
    compaction_count: int = 0

    # === Wave 0：狀態統一方法（ShellState 成為單一真相來源）===

    def set_plan_mode(self, enabled: bool) -> None:
        """切換 plan / execute 模式，並同步到 agent_session。"""
        self.plan_mode = enabled
        if self.agent_session is not None:
            self.agent_session.plan_only = enabled

    def set_chat_mode(self, new_mode: str) -> None:
        """切換 chat / agent 模式。"""
        if new_mode == "ask":
            new_mode = "agent"
        if new_mode not in {"chat", "agent"}:
            raise ValueError("mode must be 'chat' or 'agent'")
        self.mode = new_mode

    def update_settings(self, **kwargs) -> "Settings":
        """更新 settings 並回傳新設定（同時更新 agent_session 上的引用）。"""
        new_settings = self.settings.with_updates(**kwargs)
        self.settings = new_settings
        if self.agent_session is not None:
            self.agent_session.settings = new_settings
        return new_settings

    def set_persona(self, persona: str) -> None:
        """切換人格，並同步更新 agent_session + 強制清空上下文（由呼叫端決定是否重建 chat_messages）。"""
        self.update_settings(persona=persona)


app = typer.Typer(
    help="agentX local Ollama agent shell.",
    no_args_is_help=True,
    invoke_without_command=True,
)
console = Console()
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

NON_BLOCKING_COMMANDS = {"/jobs", "/cancel"}

# Module-level slash test shims live in agentx.cli_slash_shims.
# Runtime /plan, /execute, /mode, /files, /read, /search, /git, /diff logic
# lives in agentx.cli_runtime_handlers;
# nested run_shell() handlers delegate there and register into a local dict.
SLASH_HANDLERS = _slash_shims.SLASH_HANDLERS
dispatch_slash = _slash_shims.dispatch_slash
cmd_clear = _slash_shims.cmd_clear
cmd_exit = _slash_shims.cmd_exit
cmd_files = _slash_shims.cmd_files
cmd_mode = _slash_shims.cmd_mode
cmd_plan = _slash_shims.cmd_plan
cmd_quit = _slash_shims.cmd_quit


GUIDE_MODE_ROWS = [
    ("chat", "純聊天 / 解釋概念", "uv run agentx chat \"只回一句話：你是什麼？\""),
    ("ask", "單次 agent 任務", "uv run agentx ask \"幫我找出這個 repo 的測試指令\""),
    ("shell", "長時間協作 CLI", "ax"),
]

GUIDE_WORKFLOW_ROWS = [
    ("了解專案", "/files  →  /read README.md  →  /search 關鍵字"),
    ("檢查變更", "/git  →  /diff  →  /test  →  /review"),
    ("安全執行", "/tools 看風險  →  /approval strict  →  /run allowlist 指令"),
    ("延續工作", "/sessions  →  /resume latest  →  /handoff 本輪重點"),
]

WORKFLOW_ROWS = [
    ("理解 repo", "/guide  →  /files  →  /read README.md  →  /search 關鍵字"),
    ("小步修改", "/task add 目標  →  /mode ask  →  讓 agent 讀檔與改檔  →  /diff"),
    ("安全執行", "/tools  →  /approval strict  →  /run uv run pytest -q"),
    ("工程驗證", "/git  →  /diff  →  /test  →  /review"),
    ("Docker 檢查", "/docker ps  →  /docker build  →  /docker up  →  /docker logs"),
    ("記憶交接", "/sessions  →  /resume latest  →  /handoff 完成與待辦"),
    ("Headless bundle", "agentx -p \"任務\" --agent --artifact-dir .agentx/runs/latest --quiet  →  agentx handoff-resume .agentx/runs/latest --dry-run"),
    ("Infra preflight", "agentx infra resource-bundle --json  →  /intent SSH/deploy/cross-machine  →  填寫 runtime state block"),
    ("Approval audit", "/sessions  →  /transcript approvals latest --denied  →  /transcript approvals SESSION"),
    ("提交收尾", "/review  →  /commit 中文訊息"),
]


WORKFLOW_ALIASES = {
    "repo": "理解 repo",
    "understand": "理解 repo",
    "edit": "小步修改",
    "modify": "小步修改",
    "safe": "安全執行",
    "verify": "工程驗證",
    "test": "工程驗證",
    "docker": "Docker 檢查",
    "handoff": "記憶交接",
    "memory": "記憶交接",
    "headless": "Headless bundle",
    "bundle": "Headless bundle",
    "resume": "Headless bundle",
    "infra": "Infra preflight",
    "resource": "Infra preflight",
    "resource-map": "Infra preflight",
    "home-ai": "Infra preflight",
    "vps": "Infra preflight",
    "deploy": "Infra preflight",
    "ssh": "Infra preflight",
    "audit": "Approval audit",
    "approval": "Approval audit",
    "commit": "提交收尾",
}


def workflow_recipe(name: str) -> tuple[str, str] | None:
    query = name.strip()
    if not query:
        return None
    normalized = query.lower()
    wanted = WORKFLOW_ALIASES.get(normalized, query)
    for goal, path in WORKFLOW_ROWS:
        if goal == wanted or goal.lower() == normalized:
            return goal, path
    return None


def format_workflow_recipe(name: str) -> str:
    recipe = workflow_recipe(name)
    if recipe is None:
        available = ", ".join(goal for goal, _ in WORKFLOW_ROWS)
        aliases = ", ".join(sorted(WORKFLOW_ALIASES))
        return f"workflow not found: {name}\navailable: {available}\naliases: {aliases}"
    goal, path = recipe
    return f"{goal}\n{path}"


def workflow_catalog_payload(query: str | None = None) -> dict[str, object]:
    normalized_query = (query or "").strip()
    settings = Settings()
    recipes = []
    for goal, path in WORKFLOW_ROWS:
        aliases = sorted(alias for alias, target in WORKFLOW_ALIASES.items() if target == goal)
        steps = _workflow_steps(path, settings=settings)
        recipes.append(
            {
                "goal": goal,
                "path": path,
                "steps": steps,
                "commands": [str(step["command"]) for step in steps if step["runnable"]],
                "aliases": aliases,
            }
        )
    if normalized_query:
        recipe = workflow_recipe(normalized_query)
        recipes = [
            item
            for item in recipes
            if recipe is not None and item["goal"] == recipe[0]
        ]
    return {
        "schema": "agentx.workflow_catalog.v1",
        "query": normalized_query or None,
        "count": len(recipes),
        "workflows": recipes,
    }


def _workflow_steps(path: str, *, settings: Settings) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for raw_step in path.split("→"):
        command = raw_step.strip()
        if command.startswith("/"):
            steps.append({"command": command, "kind": "slash_command", "runnable": True})
        elif command.startswith("agentx "):
            steps.append(
                {
                    "command": command,
                    "kind": "agentx_cli",
                    "runnable": True,
                    "command_plan": command_plan_payload(settings, command),
                }
            )
        else:
            steps.append({"command": command, "kind": "instruction", "runnable": False})
    return steps


def print_workflow_catalog(
    query: str | None = None,
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    payload = workflow_catalog_payload(query)
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="workflows",
        )
        return
    if query and not payload["workflows"]:
        print_raw(format_workflow_recipe(query))
        return
    table = Table(title="agentX workflows", show_header=True, header_style="bold")
    table.add_column("Goal", style="cyan", no_wrap=True)
    table.add_column("Path")
    table.add_column("Aliases")
    for item in payload["workflows"]:  # type: ignore[index]
        workflow = dict(item)
        table.add_row(
            str(workflow["goal"]),
            str(workflow["path"]),
            ", ".join(str(alias) for alias in workflow["aliases"]),
        )
    console.print(table)


def print_trace(message: str) -> None:
    console.print(f"[dim][trace] {escape(message)}[/dim]")


def slash_command_hint() -> Columns:
    """回傳用 Columns 自動排版的指令列表（更漂亮）"""
    commands = [command for command, _ in SLASH_COMMANDS]
    # 轉成帶樣式的 Text
    texts = [Text(cmd, style="cyan") for cmd in commands]
    # equal=True 讓每欄寬度一致，expand=True 讓它盡量填滿
    return Columns(texts, equal=True, expand=True, column_first=True)


def print_slash_help(topic: str = "") -> None:
    """Print slash commands grouped by category with risk/safety hints.

    This is a direct step toward the vision in Image 02 & 03:
    - Clear mental models and discoverability
    - Risk awareness baked into the help experience
    """
    if topic.strip():
        command = normalize_slash_command_topic(topic)
        console.print(Panel(slash_command_help(topic), title=f"Slash Help {command}", border_style="cyan", padding=(0, 1)))
        return

    # Category definitions (vision-aligned grouping)
    categories = [
        ("核心與模式", [
            "/help", "/commands", "/guide", "/workflows", "/status", "/mode", "/plan", "/execute", "/clear", "/exit",
        ]),
        ("檔案與內容", [
            "/files", "/read", "/find", "/where", "/infra", "/intent", "/plan-task", "/grep", "/search", "/attach", "/fetch",
        ]),
        ("Git 與變更", [
            "/git", "/diff", "/stage", "/unstage", "/push", "/apply", "/commit",
        ]),
        ("記憶與交接 (Memory Hall)", [
            "/memory", "/remember", "/handoff", "/resume", "/sessions", "/transcript",
        ]),
        ("安全與核准 (Safety)", [
            "/approval", "/run", "/docker", "/test",
        ]),
        ("診斷與維護", [
            "/doctor", "/init", "/config", "/context", "/compact", "/jobs", "/cancel",
        ]),
        ("其他", [
            "/history", "/models", "/model", "/persona", "/review",
        ]),
    ]

    # Build a quick lookup
    cmd_to_desc = {command.split()[0]: desc for command, desc in SLASH_COMMANDS}

    # Stronger visual header for slash help (vision polish)
    header = Panel(
        "[bold]agentX slash commands[/bold]\n"
        "輸入指令即可使用，許多操作會依風險等級要求確認\n"
        "用 /help COMMAND 查看單一命令的 usage、examples、risk 與 related commands\n\n"
        "[green]GREEN 自動執行[/green] ｜ [yellow]YELLOW 需注意[/yellow] ｜ [red]RED 預設受保護[/red]",
        border_style="dim",
        padding=(0, 1),
    )
    console.print(header)
    console.print()

    for cat_name, cmds in categories:
        items = [(c, cmd_to_desc.get(c, "")) for c in cmds if c in cmd_to_desc]
        if not items:
            continue

        # Use Panel for visual consistency with /tools (stronger card-like feel toward Image 03)
        inner = Table(show_header=True, header_style="bold")
        inner.add_column("Command", style="cyan", no_wrap=True)
        inner.add_column("說明")

        for cmd, desc in items:
            if cmd in {"/approval", "/apply", "/commit", "/docker", "/run"}:
                desc = f"[yellow]{desc}[/yellow]"
            inner.add_row(cmd, desc)

        panel = Panel(inner, title=cat_name, border_style="dim", padding=(0, 1))
        console.print(panel)
        console.print()  # spacing between sections

    console.print("[dim]安全是 agentX 的核心 —— 你永遠可以透過 /approval 隨時調整。輸入 /doctor 查看目前姿勢。[/dim]")


def print_guide() -> None:
    """Print the 60-second orientation guide for new or returning users."""
    console.print(
        Panel(
            "[bold]agentX 60 秒導覽[/bold]\n"
            "本地 Ollama agent shell：用清楚模式、受控工具、Memory Hall 交接，"
            "把本地模型變成可長時間協作的 CLI 助手。",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    console.print()

    mode_table = Table(title="先選模式", show_header=True, header_style="bold")
    mode_table.add_column("模式", style="cyan", no_wrap=True)
    mode_table.add_column("適合情境")
    mode_table.add_column("啟動範例")
    for mode_name, scenario, example in GUIDE_MODE_ROWS:
        mode_table.add_row(mode_name, scenario, example)
    console.print(mode_table)
    console.print()

    workflow_table = Table(title="常用工作流", show_header=True, header_style="bold")
    workflow_table.add_column("目標", style="cyan", no_wrap=True)
    workflow_table.add_column("建議路徑")
    for goal, path in GUIDE_WORKFLOW_ROWS:
        workflow_table.add_row(goal, path)
    console.print(workflow_table)
    console.print()

    safety = Table(title="安全與記憶", show_header=False)
    safety.add_column("項目", style="bold cyan", no_wrap=True)
    safety.add_column("說明")
    safety.add_row("GREEN", "讀取、搜尋、git status/diff 等低風險操作會自動執行。")
    safety.add_row("YELLOW", "改檔、Docker build/up/down、Memory write 依 /approval 策略確認。")
    safety.add_row("RED", "危險操作與敏感路徑預設受保護。")
    safety.add_row("Memory Hall", "用 /remember 寫入重點，用 /handoff 交接，用 /resume 延續上一輪。")
    console.print(safety)
    console.print("[dim]下一步：輸入 /workflows 看實務路徑，/help 看全部指令，或 /tools 看工具與風險分級。[/dim]")


def print_workflows() -> None:
    """Print practical recipes for common repo workflows."""
    console.print(
        Panel(
            "[bold]agentX workflows[/bold]\n"
            "常用路徑以可驗證、可交接、可回復為主；需要改動時先看風險與 diff。",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    table = Table(title="實務工作流", show_header=True, header_style="bold")
    table.add_column("目標", style="cyan", no_wrap=True)
    table.add_column("建議路徑")
    for goal, path in WORKFLOW_ROWS:
        table.add_row(goal, path)
    console.print(table)
    console.print("[dim]提示：/mode ask 與 /mode agent 使用同一個工具模式；ask 是面向使用者的命名。[/dim]")


def print_tools(tools: ToolRegistry, query: str | None = None) -> None:
    """Print tools with risk level (GREEN / YELLOW / RED) for better discoverability.
    This moves us closer to the vision in Image 03.
    """
    tool_infos = filtered_tool_infos(tools.describe_tool_infos(), query)

    # Group by risk for clearer presentation (vision alignment)
    by_risk: dict[str, list] = {"GREEN": [], "YELLOW": [], "RED": [], "UNKNOWN": []}
    for t in tool_infos:
        by_risk.get(t["risk"], by_risk["UNKNOWN"]).append(t)

    # Render with risk color emphasis
    for risk in ["GREEN", "YELLOW", "RED", "UNKNOWN"]:
        items = by_risk.get(risk, [])
        if not items:
            continue

        risk_style = {
            "GREEN": "green",
            "YELLOW": "yellow",
            "RED": "red",
            "UNKNOWN": "dim",
        }.get(risk, "white")

        # Use Panel for stronger visual separation (closer to Image 03 card-style feel)
        inner_table = Table(show_header=True, header_style="bold")
        inner_table.add_column("Tool", style="cyan", no_wrap=True)
        inner_table.add_column("說明")

        for t in items:
            inner_table.add_row(t["name"], t["description"])

        panel = Panel(
            inner_table,
            title=f"[{risk_style}]{risk}[/{risk_style}] 工具",
            border_style=risk_style,
            padding=(0, 1),
        )
        console.print(panel)
        console.print()  # breathing room

    console.print("[dim]風險由內建機制自動判斷。想調整 YELLOW 行為請用 /approval。[/dim]")


def tool_catalog_payload(tools: ToolRegistry, query: str | None = None) -> dict[str, object]:
    infos = filtered_tool_infos(tools.describe_tool_infos(), query)
    by_risk = {
        risk: sum(1 for item in infos if item["risk"] == risk)
        for risk in ("GREEN", "YELLOW", "RED")
    }
    return {
        "schema": "agentx.tool_catalog.v1",
        "query": query or "",
        "count": len(infos),
        "by_risk": by_risk,
        "tools": infos,
    }


def filtered_tool_infos(infos: list[dict[str, object]], query: str | None = None) -> list[dict[str, object]]:
    normalized = (query or "").strip().lower()
    if not normalized:
        return infos
    risk_query = normalized.upper()
    if risk_query in {"GREEN", "YELLOW", "RED"}:
        return [item for item in infos if item["risk"] == risk_query]
    return [item for item in infos if _tool_info_matches(item, normalized)]


def _tool_info_matches(item: dict[str, object], query: str) -> bool:
    aliases = item.get("aliases", [])
    alias_text = " ".join(str(alias) for alias in aliases) if isinstance(aliases, list) else str(aliases)
    haystack = " ".join(
        [
            str(item.get("name", "")),
            str(item.get("description", "")),
            str(item.get("risk", "")),
            str(item.get("signature", "")),
            alias_text,
        ]
    ).lower()
    return query in haystack


def print_tool_catalog(
    tools: ToolRegistry,
    query: str | None = None,
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            tool_catalog_payload(tools, query),
            output_format="jsonl" if jsonl_output else "json",
            event="tools",
        )
        return
    if query:
        console.print(f"[bold]agentX tool catalog: {escape(query)}[/bold]")
    print_tools(tools, query)


def infra_payload(
    map_key: str = "all",
    *,
    per_file_chars: int = 5000,
    max_chars: int = 14000,
) -> dict[str, object]:
    metadata = infrastructure_context_metadata(map_key)
    content = build_infrastructure_context(
        map_key,
        per_file_chars=per_file_chars,
        max_chars=max_chars,
    )
    return {
        "schema": "agentx.infrastructure_context.v1",
        "map": map_key,
        "resolved_map": metadata["resolved_map"],
        "alias_applied": metadata["alias_applied"],
        "ok": True,
        "read_only": True,
        "source_status": metadata["source_status"],
        "selected_maps": metadata["selected_maps"],
        "sources": metadata["sources"],
        "limits": {
            "per_file_chars": per_file_chars,
            "max_chars": max_chars,
        },
        "content": content,
        "next_commands": [
            "Fill runtime state before SSH/deploy/cross-machine actions",
            "Use explicit Maki approval before external writes, deploy, restart, or production changes",
        ],
    }


def print_infra_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output or jsonl_output:
        output_format = "jsonl" if jsonl_output else "json"
        print_structured_payload(payload, output_format=output_format, event="infra")
        return
    print_raw(str(payload["content"]))


def _is_recursive_flag(token: str) -> bool:
    return token == "-R" or (token.startswith("-") and "R" in token[1:])


def _destructive_command_blockers(argv: list[str]) -> list[str]:
    if not argv:
        return []
    blockers: list[str] = []
    executable = Path(argv[0]).name
    if any(token in {"--delete", "--remove-source-files"} for token in argv):
        blockers.append("destructive_transfer_flag")
    if executable in {"rm", "rmdir", "unlink", "trash"}:
        blockers.append("destructive_delete_command")
    if executable == "find" and "-delete" in argv:
        blockers.append("destructive_find_delete")
    if argv[:2] == ["git", "clean"]:
        blockers.append("destructive_git_clean")
    if argv[:2] == ["git", "reset"] and "--hard" in argv:
        blockers.append("destructive_git_reset_hard")
    if argv[:2] == ["git", "push"] and any(
        token in {"--force", "--force-with-lease", "-f"} or token.startswith("--force-with-lease=")
        for token in argv[2:]
    ):
        blockers.append("destructive_git_force_push")
    if executable in {"chmod", "chown"} and any(_is_recursive_flag(token) for token in argv[1:]):
        blockers.append("destructive_recursive_permission_change")
    return blockers


def _docker_plan(settings: Settings, argv: list[str]) -> dict[str, object] | None:
    if len(argv) < 3 or argv[:2] != ["docker", "compose"]:
        return None
    action = argv[2]
    if action not in DOCKER_COMPOSE_ACTIONS:
        return {
            "matched": False,
            "blockers": ["docker_compose_action_not_allowlisted"],
            "warnings": [],
        }
    try:
        resolved_argv = docker_compose_command(settings.workspace, action)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "matched": True,
            "blockers": ["docker_compose_unavailable"],
            "warnings": [str(exc)],
            "action": action,
            "tool": f"docker_compose_{action}",
            "tool_args": {"compose_file": None},
        }
    risk = "GREEN" if action in {"ps", "logs"} else "YELLOW"
    return {
        "matched": True,
        "blockers": [],
        "warnings": [],
        "action": action,
        "risk": risk,
        "approval_required": risk == "YELLOW",
        "matched_policy": "docker_compose",
        "tool": f"docker_compose_{action}",
        "tool_args": {"compose_file": None},
        "resolved_argv": resolved_argv,
    }


def _risk_label_from_capability(capability: dict[str, object]) -> str:
    risk_text = str(capability.get("risk") or "UNKNOWN").upper()
    if "RED" in risk_text:
        return "RED"
    if "YELLOW" in risk_text:
        return "YELLOW"
    if "GREEN" in risk_text:
        return "GREEN"
    return "UNKNOWN"


def _agentx_headless_tool_args(argv: list[str]) -> dict[str, object]:
    output_format = "json" if "--json" in argv else "plain"
    output_format_option = _option_value(argv, "--output-format")
    if output_format_option:
        output_format = output_format_option
    prompt_sources = _agentx_headless_prompt_sources(argv)
    prompt_source = prompt_sources[0] if len(prompt_sources) == 1 else "multiple"
    return {
        "agent_mode": "--agent" in argv,
        "prompt_source": prompt_source,
        "prompt_source_count": len(prompt_sources),
        "prompt_file": _option_value(argv, "--prompt-file"),
        "workspace_override": _has_option(argv, "--workspace") or _has_option(argv, "--cwd"),
        "artifact_dir": _option_value(argv, "--artifact-dir"),
        "result_output": _option_value(argv, "--result-output"),
        "session_output": _option_value(argv, "--session-output"),
        "handoff_briefing_output": _option_value(argv, "--handoff-briefing-output"),
        "save_session": "--save-session" in argv,
        "resume_session": _option_value(argv, "--resume-session"),
        "quiet": "--quiet" in argv,
        "output_format": output_format,
        "dry_run": "--dry-run" in argv,
        "plan_mode": "--plan" in argv,
        "plan_then_execute": "--plan-then-execute" in argv,
        "orchestrate": "--orchestrate" in argv,
        "no_memory": "--no-memory" in argv,
        "approval_override": _option_value(argv, "--approval"),
        "backend_override": _option_value(argv, "--backend"),
        "base_url_override": _option_value(argv, "--base-url"),
        "model_override": _option_value(argv, "--model"),
        "request_timeout": _option_value(argv, "--timeout"),
        "run_timeout": _option_value(argv, "--run-timeout"),
        "max_steps": _option_value(argv, "--max-steps"),
        "result_output_format": _option_value(argv, "--result-output-format"),
    }


def _agentx_headless_blockers(settings: Settings, tool_args: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    if int(tool_args.get("prompt_source_count", 0) or 0) > 1:
        blockers.append("headless_prompt_sources_conflict")
    if _headless_prompt_file_escapes_workspace(settings.workspace, tool_args):
        blockers.append("headless_prompt_file_escapes_workspace")
    if _headless_output_paths_conflict(tool_args):
        blockers.append("headless_output_paths_conflict")
    if _headless_paths_escape_workspace(settings.workspace, tool_args):
        blockers.append("headless_output_path_escapes_workspace")
    if tool_args.get("artifact_dir"):
        conflicting_outputs = [
            name
            for name, key in [
                ("--session-output", "session_output"),
                ("--result-output", "result_output"),
                ("--handoff-briefing-output", "handoff_briefing_output"),
            ]
            if tool_args.get(key)
        ]
        if conflicting_outputs:
            blockers.append("headless_artifact_dir_conflicts_with_output_options")
        if not tool_args.get("agent_mode"):
            blockers.append("headless_artifact_dir_requires_agent")
    if tool_args.get("handoff_briefing_output") and not tool_args.get("agent_mode"):
        blockers.append("headless_handoff_briefing_output_requires_agent")
    if tool_args.get("session_output") and tool_args.get("resume_session"):
        blockers.append("headless_session_output_conflicts_with_resume_session")
    return blockers


def _headless_prompt_file_escapes_workspace(workspace: Path, tool_args: dict[str, object]) -> bool:
    value = tool_args.get("prompt_file")
    if not value:
        return False
    try:
        resolve_inside_workspace(workspace, str(value))
    except ValueError:
        return True
    return False


def _headless_paths_escape_workspace(workspace: Path, tool_args: dict[str, object]) -> bool:
    for key in ("artifact_dir", "session_output", "result_output", "handoff_briefing_output"):
        value = tool_args.get(key)
        if not value:
            continue
        try:
            resolve_inside_workspace(workspace, str(value))
        except ValueError:
            return True
    return False


def _headless_output_paths_conflict(tool_args: dict[str, object]) -> bool:
    seen: set[str] = set()
    for key in ("session_output", "result_output", "handoff_briefing_output"):
        value = tool_args.get(key)
        if not value:
            continue
        normalized = str(value)
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def _agentx_headless_prompt_sources(argv: list[str]) -> list[str]:
    sources: list[str] = []
    if "-p" in argv or _has_option(argv, "--prompt"):
        sources.append("inline_prompt")
    if _has_option(argv, "--prompt-file"):
        sources.append("prompt_file")
    if "--stdin" in argv:
        sources.append("stdin")
    return sources


def _has_option(argv: list[str], option: str) -> bool:
    return option in argv or any(token.startswith(f"{option}=") for token in argv)


def _option_value(argv: list[str], option: str) -> str | None:
    prefix = f"{option}="
    for token in argv:
        if token.startswith(prefix):
            return token.removeprefix(prefix)
    if option not in argv:
        return None
    index = argv.index(option)
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def _agentx_command_plan(settings: Settings, argv: list[str]) -> dict[str, object] | None:
    if not argv or Path(argv[0]).name not in {"agentx", "ax"}:
        return None
    if len(argv) >= 2 and (
        argv[1] in {"-p", "--prompt", "--prompt-file", "--stdin"}
        or argv[1].startswith(("--prompt=", "--prompt-file="))
    ):
        tool_args = _agentx_headless_tool_args(argv)
        blockers = _agentx_headless_blockers(settings, tool_args)
        return {
            "matched": True,
            "risk": "YELLOW" if "--agent" in argv else "GREEN",
            "approval_required": "--agent" in argv,
            "matched_policy": "agentx_headless",
            "tool": None,
            "tool_args": tool_args,
            "resolved_argv": argv,
            "blockers": blockers,
            "warnings": [],
            "next_commands": [
                "agentx inspect --json",
                "agentx artifacts --json" if tool_args.get("artifact_dir") else "agentx next --json",
            ],
        }
    subcommand = argv[1] if len(argv) >= 2 else ""
    for capability in capabilities_payload().get("capabilities", []):  # type: ignore[union-attr]
        if not isinstance(capability, dict):
            continue
        command = str(capability.get("command") or "")
        if command == f"agentx {subcommand}":
            risk = _risk_label_from_capability(capability)
            return {
                "matched": True,
                "risk": risk,
                "approval_required": risk == "YELLOW",
                "matched_policy": "agentx_cli_capability",
                "tool": None,
                "tool_args": _agentx_capability_tool_args(capability),
                "resolved_argv": argv,
                "blockers": [],
                "warnings": [],
            }
    return {
        "matched": False,
        "risk": "UNKNOWN",
        "approval_required": False,
        "matched_policy": "agentx_cli_capability",
        "tool": None,
        "tool_args": {},
        "resolved_argv": argv,
        "blockers": ["agentx_command_not_in_capabilities"],
        "warnings": [],
}


def _agentx_capability_tool_args(capability: dict[str, object]) -> dict[str, object]:
    return {
        "capability_command": str(capability.get("command") or ""),
        "usage": str(capability.get("usage") or ""),
        "schemas": [str(schema) for schema in capability.get("schemas", [])],
        "jsonl_event": str(capability.get("jsonl_event") or ""),
        "description": str(capability.get("description") or ""),
    }


def command_plan_payload(settings: Settings, command: str) -> dict[str, object]:
    command_text = command.strip()
    blockers: list[str] = []
    warnings: list[str] = []
    detail = ""
    try:
        argv = shlex.split(command_text)
    except ValueError as exc:
        argv = []
        blockers.append("invalid_command_syntax")
        detail = str(exc)

    destructive_blockers = _destructive_command_blockers(argv)
    blockers.extend(destructive_blockers)

    payload: dict[str, object] = {
        "schema": "agentx.command_plan.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "command": command_text,
        "argv": argv,
        "ok": False,
        "allowed": False,
        "risk": "RED" if destructive_blockers else "UNKNOWN",
        "approval_required": False,
        "matched_policy": None,
        "tool": None,
        "tool_args": {},
        "resolved_argv": None,
        "blockers": blockers,
        "warnings": warnings,
        "recommended_command": None,
        "recommended_kind": None,
        "recommended_risk": None,
        "next_commands": [],
        "detail": detail,
    }

    if not command_text and "invalid_command_syntax" not in blockers:
        blockers.append("empty_command")
        payload["detail"] = "command is required"
        return _with_command_plan_recommendation(payload)

    if destructive_blockers or "invalid_command_syntax" in blockers:
        payload["next_commands"] = ["Do not execute this command; ask Maki for a safer plan or human-run deletion path"]
        return _with_command_plan_recommendation(payload)

    if command_text in ALLOWED_COMMANDS:
        payload.update(
            {
                "ok": True,
                "allowed": True,
                "risk": "GREEN",
                "approval_required": False,
                "matched_policy": "allowed_command",
                "tool": "run_command",
                "tool_args": {"command": command_text},
                "resolved_argv": ALLOWED_COMMANDS[command_text],
                "next_commands": [f"/run {command_text}"],
            }
        )
        return _with_command_plan_recommendation(payload)

    if command_text in BUILD_COMMANDS:
        payload.update(
            {
                "ok": True,
                "allowed": True,
                "risk": "YELLOW",
                "approval_required": True,
                "matched_policy": "build_command",
                "tool": "run_build_command",
                "tool_args": {"command": command_text},
                "resolved_argv": BUILD_COMMANDS[command_text],
                "next_commands": [f"/run {command_text}", "Confirm YELLOW approval before execution"],
            }
        )
        return _with_command_plan_recommendation(payload)

    docker_plan = _docker_plan(settings, argv)
    if docker_plan is not None:
        blockers.extend(str(item) for item in docker_plan.get("blockers", []))
        warnings.extend(str(item) for item in docker_plan.get("warnings", []))
        action = str(docker_plan.get("action") or "")
        if docker_plan.get("matched") and not blockers:
            payload.update(
                {
                    "ok": True,
                    "allowed": True,
                    "risk": docker_plan["risk"],
                    "approval_required": docker_plan["approval_required"],
                    "matched_policy": docker_plan["matched_policy"],
                    "tool": docker_plan["tool"],
                    "tool_args": docker_plan["tool_args"],
                    "resolved_argv": docker_plan["resolved_argv"],
                    "next_commands": [f"/docker {action}"],
                }
            )
        else:
            payload.update(
                {
                    "risk": "UNKNOWN",
                    "matched_policy": "docker_compose",
                    "tool": docker_plan.get("tool"),
                    "tool_args": docker_plan.get("tool_args", {}),
                    "next_commands": ["Check compose file and use /docker ps|build|up|logs|down"],
                }
            )
        return _with_command_plan_recommendation(payload)

    agentx_plan = _agentx_command_plan(settings, argv)
    if agentx_plan is not None:
        blockers.extend(str(item) for item in agentx_plan.get("blockers", []))
        warnings.extend(str(item) for item in agentx_plan.get("warnings", []))
        if agentx_plan.get("matched") and not blockers:
            payload.update(
                {
                    "ok": True,
                    "allowed": True,
                    "risk": agentx_plan["risk"],
                    "approval_required": agentx_plan["approval_required"],
                    "matched_policy": agentx_plan["matched_policy"],
                    "tool": agentx_plan["tool"],
                    "tool_args": agentx_plan["tool_args"],
                    "resolved_argv": agentx_plan["resolved_argv"],
                    "next_commands": agentx_plan.get(
                        "next_commands",
                        ["Run through agentX CLI policy; do not bypass approval gates"],
                    ),
                }
            )
        else:
            payload.update(
                {
                    "risk": "UNKNOWN",
                    "matched_policy": agentx_plan.get("matched_policy"),
                    "tool": agentx_plan.get("tool"),
                    "tool_args": agentx_plan.get("tool_args", {}),
                    "resolved_argv": agentx_plan.get("resolved_argv"),
                    "next_commands": ["agentx capabilities --json"],
                }
            )
        return _with_command_plan_recommendation(payload)

    blockers.append("command_not_allowlisted")
    payload["detail"] = "Command is not in ALLOWED_COMMANDS, BUILD_COMMANDS, docker compose policy, or agentx CLI capabilities"
    payload["next_commands"] = ["Use agentx tools --json to inspect runnable tools", "Ask Maki before expanding command policy"]
    return _with_command_plan_recommendation(payload)


def _with_command_plan_recommendation(payload: dict[str, object]) -> dict[str, object]:
    next_commands = payload.get("next_commands")
    recommended_command = str(next_commands[0]) if isinstance(next_commands, list) and next_commands else None
    if recommended_command is None:
        payload["recommended_command"] = None
        payload["recommended_kind"] = None
        payload["recommended_risk"] = None
        return payload

    blockers = payload.get("blockers")
    risk = str(payload.get("risk") or "UNKNOWN")
    matched_policy = str(payload.get("matched_policy") or "")
    tool = str(payload.get("tool") or "")
    if isinstance(blockers, list) and blockers:
        kind = "do_not_execute" if risk == "RED" else "fix_blockers"
    elif matched_policy == "allowed_command":
        kind = "run_command"
    elif matched_policy == "build_command":
        kind = "run_build_command"
    elif matched_policy == "docker_compose":
        kind = tool or "docker_compose"
    elif matched_policy == "agentx_headless":
        kind = "agentx_headless"
    elif matched_policy == "agentx_cli_capability":
        kind = "agentx_cli"
    else:
        kind = "inspect_tools"

    payload["recommended_command"] = recommended_command
    payload["recommended_kind"] = kind
    payload["recommended_risk"] = risk
    return payload


def command_plan_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    return 1 if fail_on_blocker and payload.get("blockers") else 0


def print_command_plan_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output or jsonl_output:
        output_format = "jsonl" if jsonl_output else "json"
        print_structured_payload(payload, output_format=output_format, event="command_plan")
        return
    status = "allowed" if payload.get("allowed") else "blocked"
    print_raw(f"{status}: {payload.get('command')}")
    print_raw(f"risk: {payload.get('risk')}")
    if payload.get("tool"):
        print_raw(f"tool: {payload.get('tool')}")
    blockers = payload.get("blockers") or []
    if blockers:
        print_raw("blockers:")
        for blocker in blockers:
            print_raw(f"- {blocker}")
    next_commands = payload.get("next_commands") or []
    if next_commands:
        print_raw("next:")
        for command_item in next_commands:
            print_raw(f"- {command_item}")


def _parse_tool_args(args_json: str | None) -> tuple[dict[str, object], list[str], str]:
    raw = (args_json or "{}").strip()
    if not raw:
        return {}, [], ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, ["invalid_args_json"], str(exc)
    if not isinstance(parsed, dict):
        return {}, ["tool_args_must_be_object"], "tool args JSON must decode to an object"
    return parsed, [], ""


def _coerce_path_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _tool_plan_arg_blockers(settings: Settings, canonical_tool: str, args: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    if canonical_tool in {"write_file", "edit_file", "insert_code"}:
        path_value = args.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            return ["missing_path"]
        if canonical_tool == "write_file" and not isinstance(args.get("content"), str):
            blockers.append("missing_content")
        if canonical_tool == "edit_file":
            edits = args.get("edits")
            if not isinstance(edits, list) or not edits:
                blockers.append("missing_edits")
        if canonical_tool == "insert_code":
            if not isinstance(args.get("insert_after"), str) or not str(args.get("insert_after") or "").strip():
                blockers.append("missing_insert_after")
            if not isinstance(args.get("content"), str):
                blockers.append("missing_content")
        try:
            target = resolve_inside_workspace(settings.workspace, path_value)
            ensure_safe_write_path(settings.workspace, target)
        except ValueError:
            blockers.append("unsafe_write_path")
    elif canonical_tool in {"git_stage", "git_unstage"}:
        paths = _coerce_path_list(args.get("paths"))
        if not paths:
            return ["missing_paths"]
        for path in paths:
            if path in {"", "."} or any(ch in path for ch in "*?[]"):
                blockers.append("unsafe_git_path")
                break
            try:
                resolve_inside_workspace(settings.workspace, path)
            except ValueError:
                blockers.append("unsafe_git_path")
                break
    elif canonical_tool in {"run_command", "run_build_command"}:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ["missing_command"]
        command_plan = command_plan_payload(settings, command)
        if command_plan.get("blockers"):
            blockers.extend(str(item) for item in command_plan["blockers"])  # type: ignore[index]
        if canonical_tool == "run_command" and command_plan.get("matched_policy") != "allowed_command":
            blockers.append("run_command_requires_green_allowlist")
        if canonical_tool == "run_build_command" and command_plan.get("matched_policy") != "build_command":
            blockers.append("run_build_command_requires_build_allowlist")
    elif canonical_tool.startswith("docker_compose_"):
        action = canonical_tool.removeprefix("docker_compose_")
        try:
            docker_compose_command(
                settings.workspace,
                action,
                compose_file=str(args["compose_file"]) if args.get("compose_file") is not None else None,
                service=str(args["service"]) if args.get("service") is not None else None,
                tail=int(args.get("tail", 100)),
            )
        except (FileNotFoundError, ValueError):
            blockers.append("docker_compose_unavailable")
    return blockers


def _tool_plan_embedded_command_plan(
    settings: Settings,
    canonical_tool: str | None,
    args: dict[str, object],
) -> dict[str, object] | None:
    if canonical_tool not in {"run_command", "run_build_command"}:
        return None
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    return command_plan_payload(settings, command)


def tool_plan_payload(settings: Settings, tool_name: str, args_json: str | None = None) -> dict[str, object]:
    registry = ToolRegistry(builtin_tools(settings.workspace, NullMemoryClient()))
    args, blockers, detail = _parse_tool_args(args_json)
    requested_tool = tool_name.strip()
    tool = registry.get(requested_tool) if requested_tool else None
    canonical_tool = getattr(tool, "name", None) if tool is not None else None
    risk = getattr(tool, "risk", None)
    enabled = tool_is_enabled(tool) if tool is not None else False

    payload: dict[str, object] = {
        "schema": "agentx.tool_plan.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "requested_tool": requested_tool,
        "canonical_tool": canonical_tool,
        "exists": tool is not None,
        "enabled": enabled,
        "ok": False,
        "risk": risk.value if risk is not None else "UNKNOWN",
        "approval_required": risk == Risk.YELLOW if risk is not None else False,
        "args": args,
        "signature": tool_signature(tool) if tool is not None else "",
        "description": str(getattr(tool, "description", "")) if tool is not None else "",
        "aliases": tool_aliases(tool) if tool is not None else [],
        "command_plan": _tool_plan_embedded_command_plan(settings, canonical_tool, args),
        "blockers": blockers,
        "warnings": [],
        "next_commands": [],
        "detail": detail,
    }

    if not requested_tool:
        blockers.append("missing_tool")
    elif tool is None:
        blockers.append("unknown_tool")
        payload["next_commands"] = ["agentx tools --json"]
    elif not enabled:
        blockers.append("tool_disabled")
    elif risk == Risk.RED:
        blockers.append("red_tool_blocked")
    elif not blockers and canonical_tool is not None:
        blockers.extend(_tool_plan_arg_blockers(settings, canonical_tool, args))

    if not blockers and tool is not None:
        payload["ok"] = True
        if risk == Risk.YELLOW:
            payload["next_commands"] = ["Confirm YELLOW approval before execution"]
        else:
            payload["next_commands"] = ["Tool call is preflight-clean; execute only through agentX tool policy"]
    return payload


def tool_plan_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    return 1 if fail_on_blocker and payload.get("blockers") else 0


def print_tool_plan_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output or jsonl_output:
        output_format = "jsonl" if jsonl_output else "json"
        print_structured_payload(payload, output_format=output_format, event="tool_plan")
        return
    status = "ok" if payload.get("ok") else "blocked"
    print_raw(f"{status}: {payload.get('requested_tool')} -> {payload.get('canonical_tool')}")
    print_raw(f"risk: {payload.get('risk')}")
    blockers = payload.get("blockers") or []
    if blockers:
        print_raw("blockers:")
        for blocker in blockers:
            print_raw(f"- {blocker}")


def print_raw(text: object) -> None:
    console.print(ANSI_RE.sub("", str(text)), markup=False, highlight=False)


def print_json_output(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


def print_delta(text: object) -> None:
    console.print(ANSI_RE.sub("", str(text)), markup=False, highlight=False, end="")


def print_block(text: object) -> None:
    print_raw(f"\n{text}\n")


def print_context(agent_session: AgentSession, chat_messages: list[dict[str, str]]) -> None:
    report = agent_session.context_report()
    table = Table(title="agentX context", show_header=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("namespace", str(report["namespace"]))
    table.add_row("agent messages", str(report["messages"]))
    table.add_row("agent chars", str(report["chars"]))
    table.add_row("agent tokens estimate", str(report["tokens_estimate"]))
    table.add_row("compactions", str(report["compactions"]))
    table.add_row("chat messages", str(len(chat_messages)))
    table.add_row("chat tokens estimate", str(sum(len(m.get("content", "")) for m in chat_messages) // 4))
    console.print(table)


def context_percent(
    settings: Settings,
    agent_session: AgentSession,
    chat_messages: list[dict[str, str]],
) -> int:
    chat_tokens = sum(len(m.get("content", "")) for m in chat_messages) // 4
    used_tokens = max(agent_session.context_tokens_estimate, chat_tokens)
    if settings.context_limit_tokens <= 0:
        return 0
    return min(999, round((used_tokens / settings.context_limit_tokens) * 100))


def print_history(history: list[tuple[str, str]]) -> None:
    table = Table(title="agentX session history", show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Mode", style="cyan", no_wrap=True)
    table.add_column("Prompt")
    for index, (mode, prompt) in enumerate(history[-20:], start=max(1, len(history) - 19)):
        table.add_row(str(index), mode, prompt[:120])
    console.print(table)


def print_jobs(job_queue: PromptJobQueue) -> None:
    table = Table(title="agentX jobs", show_header=True, header_style="bold")
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("State", style="cyan", no_wrap=True)
    table.add_column("Prompt")
    current = job_queue.current
    if current is not None:
        table.add_row(str(current.id), "running", current.prompt[:120])
    for job in job_queue.pending():
        table.add_row(str(job.id), "queued", job.prompt[:120])
    if current is None and not job_queue.pending():
        table.add_row("-", "idle", "(none)")
    console.print(table)


def cancel_jobs(
    job_queue: PromptJobQueue,
    value: str | None,
    current_cancel: threading.Event | None = None,
) -> str:
    if value == "current":
        if job_queue.current is None or current_cancel is None:
            return "no running job to cancel"
        current_cancel.set()
        return f"cancelling running job: {job_queue.current.id}"
    if value in (None, "", "all"):
        cancelled = job_queue.cancel_pending()
    else:
        try:
            job_id = int(value)
        except ValueError:
            return "usage: /cancel [JOB_ID|all]"
        cancelled = job_queue.cancel_pending(job_id)
    if not cancelled:
        return "no queued jobs cancelled"
    ids = ", ".join(str(job.id) for job in cancelled)
    return f"cancelled queued jobs: {ids}"


def handle_keyboard_interrupt(
    job_queue: PromptJobQueue,
    current_cancel: threading.Event | None = None,
) -> str | None:
    """Return an interrupt message, or None when Ctrl+C should exit the shell."""
    if job_queue.current is not None:
        if current_cancel is not None:
            current_cancel.set()
        cancelled = job_queue.cancel_pending()
        suffix = ""
        if cancelled:
            ids = ", ".join(str(job.id) for job in cancelled)
            suffix = f"; cancelled queued jobs: {ids}"
        return f"cancelling running job: {job_queue.current.id}{suffix}"

    cancelled = job_queue.cancel_pending()
    if cancelled:
        ids = ", ".join(str(job.id) for job in cancelled)
        return f"cancelled queued jobs: {ids}"

    return None


def apply_plan_task(workspace: Path, request: str) -> str:
    text = request.strip()
    if not text:
        return "usage: /plan-task --apply TEXT"

    tasks = load_tasks(workspace)
    next_id = get_next_task_id(tasks)
    new_tasks = []
    for index, description in enumerate(plan_task_items(text)):
        new_tasks.append(
            {
                "id": next_id + index,
                "description": description[:200],
                "status": "in_progress" if index == 0 else "pending",
                "notes": "[來自 /plan-task --apply]",
            }
        )
    tasks.extend(new_tasks)
    save_tasks(workspace, tasks)

    lines = [f"已新增 {len(new_tasks)} 個任務："]
    for task in new_tasks:
        lines.append(f"- #{task['id']} [{task['status']}] {task['description']}")
    return "\n".join(lines)


def print_sessions(settings: Settings) -> None:
    payload = sessions_payload(settings)
    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Start")
    table.add_column("Model")
    table.add_column("Namespace")
    table.add_column("Turns", justify="right")
    table.add_column("Approval", justify="right")
    table.add_column("Last")
    for overview in payload["sessions"]:  # type: ignore[index]
        table.add_row(
            str(overview["name"]),
            str(overview["started"]),
            str(overview["model"]),
            str(overview["namespace"]),
            str(overview["turns"]),
            str(overview["approval"]),
            str(overview["last"]),
        )
    console.print(table)
    console.print("[dim]使用 /resume latest 或 /resume SESSION_NAME 載入上一輪摘要。[/dim]")


def sessions_payload(settings: Settings, *, limit: int = 10) -> dict[str, object]:
    sessions = [transcript_overview(path) for path in list_transcripts(settings.workspace, limit=limit)]
    return {
        "schema": "agentx.sessions.v1",
        "workspace": str(settings.workspace),
        "count": len(sessions),
        "sessions": sessions,
    }


def resolve_artifacts_root(workspace: Path, value: str) -> Path:
    try:
        target = resolve_inside_workspace(workspace, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if target.exists() and not target.is_dir():
        raise typer.BadParameter(f"artifacts root is not a directory: {value}")
    return target


def artifact_mtime(path: Path) -> float:
    candidates = [path / "result.json", path / "result.jsonl", path / "session.session.jsonl", path / "handoff.md"]
    existing = [candidate.stat().st_mtime for candidate in candidates if candidate.exists()]
    if existing:
        return max(existing)
    return path.stat().st_mtime


def artifact_mtime_text(path: Path) -> str:
    return datetime.fromtimestamp(artifact_mtime(path)).isoformat(timespec="seconds")


def relative_workspace_path(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def read_artifact_result_payload(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        return load_headless_payload_file(path)
    except (OSError, typer.BadParameter):
        return None


def artifact_handoff_summary(result_payload: dict[str, object] | None) -> dict[str, object]:
    if not result_payload:
        return {}
    log_summary = result_payload.get("log_summary")
    if not isinstance(log_summary, dict):
        return {}
    handoff = log_summary.get("handoff_summary")
    return dict(handoff) if isinstance(handoff, dict) else {}


def artifact_bundle_overview(workspace: Path, bundle: Path) -> dict[str, object]:
    result_json = bundle / "result.json"
    result_jsonl = bundle / "result.jsonl"
    session_path = bundle / "session.session.jsonl"
    handoff_path = bundle / "handoff.md"
    result_path: Path | None = None
    result_format: str | None = None
    result_conflict = result_json.is_file() and result_jsonl.is_file()
    if result_json.is_file():
        result_path = result_json
        result_format = "json"
    elif result_jsonl.is_file():
        result_path = result_jsonl
        result_format = "jsonl"

    result_payload = read_artifact_result_payload(result_path) if result_path else None
    handoff = artifact_handoff_summary(result_payload)
    return {
        "name": bundle.name,
        "path": str(bundle),
        "relative_path": relative_workspace_path(workspace, bundle),
        "updated_at": artifact_mtime_text(bundle),
        "has_result": result_path is not None,
        "result_path": str(result_path) if result_path else None,
        "result_relative_path": relative_workspace_path(workspace, result_path) if result_path else None,
        "result_format": result_format,
        "result_conflict": result_conflict,
        "has_session": session_path.is_file(),
        "session_path": str(session_path) if session_path.is_file() else None,
        "session_relative_path": relative_workspace_path(workspace, session_path) if session_path.is_file() else None,
        "has_handoff": handoff_path.is_file(),
        "handoff_path": str(handoff_path) if handoff_path.is_file() else None,
        "handoff_relative_path": relative_workspace_path(workspace, handoff_path) if handoff_path.is_file() else None,
        "schema_version": result_payload.get("schema_version") if result_payload else None,
        "termination": result_payload.get("termination") if result_payload else None,
        "exit_code": result_payload.get("exit_code") if result_payload else None,
        "needs_handoff": bool(handoff.get("needs_handoff", False)),
        "resume_command": handoff.get("resume_command"),
    }


def is_artifact_bundle(path: Path) -> bool:
    return any(
        (path / name).is_file()
        for name in ("result.json", "result.jsonl", "session.session.jsonl", "handoff.md")
    )


def list_artifact_bundles(root: Path) -> list[Path]:
    if is_artifact_bundle(root):
        return [root]
    return [path for path in root.iterdir() if path.is_dir() and is_artifact_bundle(path)]


def artifacts_payload(settings: Settings, *, root: str = ".agentx/runs", limit: int = 20) -> dict[str, object]:
    artifact_root = resolve_artifacts_root(settings.workspace, root)
    if not artifact_root.exists():
        return {
            "schema": "agentx.artifacts.v1",
            "workspace": str(settings.workspace),
            "root": str(artifact_root),
            "root_relative_path": relative_workspace_path(settings.workspace, artifact_root),
            "ok": True,
            "limit": limit,
            "count": 0,
            "latest_artifact": None,
            "recommended_command": "agentx -p '任務' --agent --artifact-dir .agentx/runs/latest --quiet",
            "recommended_kind": "headless_bundle",
            "recommended_risk": "YELLOW",
            "artifacts": [],
            "detail": f"artifacts root not found: {root}",
        }

    bundles = sorted(list_artifact_bundles(artifact_root), key=artifact_mtime, reverse=True)[:limit]
    artifacts = [artifact_bundle_overview(settings.workspace, bundle) for bundle in bundles]
    latest_artifact = dict(artifacts[0]) if artifacts else None
    recommended_command, recommended_kind, recommended_risk = _artifacts_recommendation(latest_artifact)
    return {
        "schema": "agentx.artifacts.v1",
        "workspace": str(settings.workspace),
        "root": str(artifact_root),
        "root_relative_path": relative_workspace_path(settings.workspace, artifact_root),
        "ok": True,
        "limit": limit,
        "count": len(artifacts),
        "latest_artifact": latest_artifact,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "artifacts": artifacts,
        "detail": "",
    }


def _artifacts_recommendation(artifact: dict[str, object] | None) -> tuple[str, str, str]:
    if artifact is None:
        return (
            "agentx -p '任務' --agent --artifact-dir .agentx/runs/latest --quiet",
            "headless_bundle",
            "YELLOW",
        )
    artifact_path = str(artifact.get("relative_path") or artifact.get("path") or ".agentx/runs/latest")
    if artifact.get("needs_handoff") is True and artifact.get("resume_command"):
        return f"agentx handoff-resume {shlex.quote(artifact_path)} --dry-run", "handoff_resume", "GREEN"
    return f"agentx artifacts {shlex.quote(artifact_path)} --json", "inspect_artifact", "GREEN"


def approvals_payload(
    settings: Settings,
    *,
    session: str = "latest",
    limit: int = 20,
    denied_only: bool = False,
) -> dict[str, object]:
    """Return approval receipts from a saved transcript for headless audit."""
    path = find_transcript(settings.workspace, session)
    if path is None:
        return {
            "schema": "agentx.approvals.v1",
            "workspace": str(settings.workspace),
            "session": session,
            "ok": False,
            "path": None,
            "denied_only": denied_only,
            "limit": limit,
            "count": 0,
            "denied_count": 0,
            "receipts": [],
            "detail": f"transcript not found: {session}",
        }

    receipts = approval_receipts(path, limit=limit, denied_only=denied_only)
    denied_count = sum(1 for receipt in receipts if receipt.get("allowed") is False)
    return {
        "schema": "agentx.approvals.v1",
        "workspace": str(settings.workspace),
        "session": session,
        "ok": True,
        "path": str(path),
        "denied_only": denied_only,
        "limit": limit,
        "count": len(receipts),
        "denied_count": denied_count,
        "receipts": receipts,
        "detail": "",
    }


def read_transcript_records(path: Path) -> tuple[list[dict[str, object]], int]:
    records: list[dict[str, object]] = []
    invalid_line_count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_line_count += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                invalid_line_count += 1
    return records, invalid_line_count


def trace_event_name(record: dict[str, object]) -> str:
    event = record.get("event")
    if event:
        return str(event)
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata.get("event"):
        return str(metadata["event"])
    role = record.get("role")
    if role:
        return f"role:{role}"
    return "record"


def transcript_event_excerpt(record: dict[str, object]) -> dict[str, object]:
    excerpt: dict[str, object] = {
        "ts": record.get("ts"),
        "event": trace_event_name(record),
    }
    for key in ("mode", "command", "tool", "action", "ok", "allowed", "risk", "source", "reason"):
        if key in record:
            excerpt[key] = record.get(key)
    text = record.get("content") or record.get("result") or record.get("summary")
    if text is not None:
        excerpt["text"] = str(text).replace("\n", " ")[:240]
    return excerpt


def trace_tool_name(record: dict[str, object]) -> str | None:
    if trace_event_name(record) != "tool":
        return None
    for key in ("tool", "command", "action"):
        value = record.get(key)
        if value:
            return str(value)
    return "(unknown)"


def traces_payload(
    settings: Settings,
    *,
    session: str = "latest",
    limit: int = 20,
) -> dict[str, object]:
    path = find_transcript(settings.workspace, session)
    if path is None:
        return {
            "schema": "agentx.traces.v1",
            "workspace": str(settings.workspace),
            "session": session,
            "ok": False,
            "path": None,
            "limit": limit,
            "count": 0,
            "invalid_line_count": 0,
            "event_counts": {},
            "tool_counts": {},
            "approval_count": 0,
            "approval_denied_count": 0,
            "tool_failure_count": 0,
            "error_like_count": 0,
            "first_ts": None,
            "last_ts": None,
            "recent_events": [],
            "detail": f"transcript not found: {session}",
        }

    records, invalid_line_count = read_transcript_records(path)
    event_counts = Counter(trace_event_name(record) for record in records)
    tool_counts = Counter(
        tool_name
        for record in records
        if (tool_name := trace_tool_name(record)) is not None
    )
    approval_count = int(event_counts.get("approval", 0))
    approval_denied_count = sum(
        1 for record in records if trace_event_name(record) == "approval" and record.get("allowed") is False
    )
    tool_failure_count = sum(
        1 for record in records if trace_event_name(record) == "tool" and record.get("ok") is False
    )
    error_like_count = sum(
        1
        for record in records
        if "error" in trace_event_name(record).lower()
        or record.get("ok") is False
        or record.get("allowed") is False
    )
    timestamps = [str(record.get("ts")) for record in records if record.get("ts")]
    return {
        "schema": "agentx.traces.v1",
        "workspace": str(settings.workspace),
        "session": session,
        "ok": True,
        "path": str(path),
        "limit": limit,
        "count": len(records),
        "invalid_line_count": invalid_line_count,
        "event_counts": dict(sorted(event_counts.items())),
        "tool_counts": dict(sorted(tool_counts.items())),
        "approval_count": approval_count,
        "approval_denied_count": approval_denied_count,
        "tool_failure_count": tool_failure_count,
        "error_like_count": error_like_count,
        "first_ts": timestamps[0] if timestamps else None,
        "last_ts": timestamps[-1] if timestamps else None,
        "recent_events": [transcript_event_excerpt(record) for record in records[-limit:]],
        "detail": "",
    }


def approvals_exit_code(payload: dict[str, object], *, fail_on_denied: bool = False) -> int:
    if not fail_on_denied:
        return 0
    return 1 if int(payload.get("denied_count", 0)) > 0 else 0


def print_approvals_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="approvals",
        )
        return

    if not payload.get("ok"):
        print_raw(str(payload.get("detail", "transcript not found")))
        return

    path = Path(str(payload["path"]))
    print_raw(
        f"source: {path}\n"
        + format_approval_receipts(
            path,
            limit=int(payload["limit"]),
            denied_only=bool(payload["denied_only"]),
        )
    )


def print_traces_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="traces",
        )
        return

    if not payload.get("ok"):
        print_raw(str(payload.get("detail", "transcript not found")))
        return

    table = Table(title="agentX trace summary", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key in [
        "path",
        "count",
        "invalid_line_count",
        "first_ts",
        "last_ts",
        "approval_count",
        "approval_denied_count",
        "tool_failure_count",
        "error_like_count",
    ]:
        table.add_row(key, str(payload.get(key)))
    table.add_row("event_counts", json.dumps(payload.get("event_counts", {}), ensure_ascii=False))
    table.add_row("tool_counts", json.dumps(payload.get("tool_counts", {}), ensure_ascii=False))
    console.print(table)


def print_sessions_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="sessions",
        )
        return

    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Start")
    table.add_column("Model")
    table.add_column("Namespace")
    table.add_column("Turns", justify="right")
    table.add_column("Approval", justify="right")
    table.add_column("Last")
    for overview in payload["sessions"]:  # type: ignore[index]
        table.add_row(
            str(overview["name"]),
            str(overview["started"]),
            str(overview["model"]),
            str(overview["namespace"]),
            str(overview["turns"]),
            str(overview["approval"]),
            str(overview["last"]),
        )
    console.print(table)


def print_artifacts_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="artifacts",
        )
        return

    table = Table(title="agentX artifacts", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Updated")
    table.add_column("Result")
    table.add_column("Exit", justify="right")
    table.add_column("Termination")
    table.add_column("Handoff")
    table.add_column("Path")
    for overview in payload["artifacts"]:  # type: ignore[index]
        artifact = dict(overview)
        result = str(artifact.get("result_format") or "-")
        if artifact.get("result_conflict"):
            result = "conflict"
        table.add_row(
            str(artifact["name"]),
            str(artifact["updated_at"]),
            result,
            str(artifact.get("exit_code")),
            str(artifact.get("termination")),
            "yes" if artifact.get("needs_handoff") else "no",
            str(artifact["relative_path"]),
        )
    if not payload.get("count"):
        table.caption = str(payload.get("detail") or "No artifact bundles found.")
    console.print(table)


def print_tool_result(result_text: str) -> None:
    if result_text.strip():
        print_raw(result_text)
    else:
        console.print("[dim](no output)[/dim]")


def print_command_preview(command: list[str]) -> None:
    print_raw("final command:")
    print_raw(" ".join(shlex.quote(part) for part in command))
    print_raw("args:")
    for index, part in enumerate(command):
        print_raw(f"{index}: {part}")


def parse_docker_prompt(prompt: str) -> dict[str, object] | None:
    try:
        parts = shlex.split(prompt)
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    action = parts[1]
    if action not in DOCKER_COMPOSE_ACTIONS:
        return None
    args: dict[str, object] = {}
    if action == "logs" and len(parts) >= 3:
        args["service"] = parts[2]
    if len(parts) > 3:
        return None
    return {"action": action, **args}


def build_attachment_context(prompt: str, workspace: Path) -> tuple[str, list[str]]:
    paths = extract_file_paths(prompt, workspace)
    attachments = read_attachments(paths)
    return format_attachment_context(attachments), [str(item.path) for item in attachments]


def run_review(ollama: OllamaClient, tools: ToolRegistry) -> str:
    status = tools.run("git_status", {}).content
    diff = tools.run("git_diff", {}).content
    tests = tools.run("run_tests", {}).content
    if not diff.strip():
        return "No diff to review.\n\n" + status

    prompt = (
        "你是 code reviewer。請用 findings-first 格式，用繁體中文回覆。"
        "優先列出 bug、風險、回歸、測試缺口；如果沒有問題，明確說未發現重大問題。"
        "不要稱讚，不要寫冗長摘要。\n\n"
        f"Git status:\n{status[:4000]}\n\n"
        f"Diff:\n{diff[:20000]}\n\n"
        f"Tests:\n{tests[:8000]}"
    )
    try:
        return ollama.chat(
            [
                {"role": "system", "content": "Use Traditional Chinese. Be concise and findings-first."},
                {"role": "user", "content": prompt},
            ],
            json_mode=False,
        )
    except Exception as exc:
        return (
            f"review model call failed: {type(exc).__name__}: {exc}\n\n"
            f"Git status:\n{status}\n\nDiff:\n{diff[:12000]}\n\nTests:\n{tests}"
        )


def approve_interactive(tool: str, args: dict[str, object], risk: Risk) -> bool:
    console.print(f"[yellow]approval required[/yellow] risk={risk.value} tool={tool}")
    preview = str(args)
    console.print(preview[:1200])
    answer = typer.prompt("Approve? type yes").strip().lower()
    return answer == "yes"


def print_approval(policy: ApprovalPolicy) -> None:
    table = Table(title="agentX approval policy", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("mode", policy.mode.value)
    table.add_row("aliases", "strict=ask, auto-approve=auto, deny=off")
    table.add_row("GREEN", "auto allow")
    table.add_row("YELLOW", "ask / auto / off")
    table.add_row("RED", "always block")
    console.print(table)

    # Educational note for better safety awareness
    meaning = {
        "auto": "YELLOW 工具現在會自動執行（適合熟悉後提高效率）",
        "ask": "YELLOW 工具會詢問你是否執行（strict 目前同義，最平衡）",
        "off": "YELLOW 工具會被拒絕執行（deny 同義，最保守）",
    }.get(policy.mode.value, "")

    if meaning:
        console.print(f"[dim]→ {meaning}[/dim]")


def format_plan_status(enabled: bool) -> str:
    """Return user-friendly plan mode status string."""
    return "on（只討論方案，不使用工具）" if enabled else "off"


def build_status_line(model: str, plan_mode: bool, context_pct: int, approval: str | None = None) -> str:
    """Build the bottom status line text shown in TUI and classic prompt mode.

    Now includes optional approval mode for constant safety awareness (vision alignment).
    """
    plan_marker = " | PLAN" if plan_mode else ""
    approval_marker = ""
    if approval:
        # More readable than single cryptic symbols (still compact)
        short = {"auto": "auto", "ask": "ask", "off": "off"}.get(approval, approval)
        approval_marker = f" | safe={short}"
    return f"{model}{plan_marker}{approval_marker} | context {context_pct}%"


EXECUTE_TRIGGERS = [
    "現在執行", "執行吧", "開始執行", "go ahead",
    "執行這個方案", "執行剛剛的", "現在就做", "proceed",
    "照這個做", "照這個方案做", "這個方案做",
]

def is_natural_execute_trigger(text: str) -> bool:
    """Check if the user input looks like a natural language request to start execution."""
    text_lower = text.lower().strip()
    return any(trigger.lower() in text_lower for trigger in EXECUTE_TRIGGERS)


def print_config(
    settings: Settings,
    namespace: str,
    mode: str,
    approval_policy: ApprovalPolicy,
    memory: "MemoryHallClient | None" = None,
) -> None:
    # Use shared collector so /status, /config and /doctor all see the same live ACA signals
    # (incl. the complete post-gov audit event list for the probe governance record).
    probe_info = _collect_aca_probe_info(settings, memory)
    latest_probe_expires = probe_info["latest_probe_expires"]
    latest_probe_audit = probe_info["latest_probe_audit"]
    latest_probe_gov = probe_info["latest_probe_gov"]
    latest_probe_gov_audit_full = probe_info["latest_probe_gov_audit_full"]
    client_type = probe_info["client_type"]
    table = Table(title="agentX config", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("model", settings.model)
    table.add_row("ollama_url", settings.ollama_url)
    table.add_row("memory_backend", getattr(settings, "memory_backend", "memhall"))
    if getattr(settings, "memory_backend", "memhall") == "amh":
        table.add_row("memory_amh_store", getattr(settings, "memory_amh_store", "json"))
        table.add_row("memory_amh_path", getattr(settings, "memory_amh_path", "(default)"))
        if client_type != "N/A":
            table.add_row("記憶 client 類型 (ACA)", client_type)
    table.add_row("memory_hall_url", settings.memory_hall_url)
    table.add_row("memory_hall_token", "set" if settings.memory_hall_token else "missing")
    table.add_row("workspace", str(settings.workspace))
    table.add_row("namespace", namespace)
    table.add_row("mode", mode)
    table.add_row("approval", approval_policy.mode.value)
    table.add_row("persona", settings.persona)
    table.add_row("auto_handoff", str(settings.auto_handoff))
    table.add_row("context_limit_tokens", str(settings.context_limit_tokens))
    project_config = load_project_config(settings.workspace)
    table.add_row("config_file_model", str(project_config.model))
    table.add_row("config_file_namespace", str(project_config.namespace))
    table.add_row("config_file_mode", str(project_config.mode))
    table.add_row("config_file_approval", str(project_config.approval))
    table.add_row("config_file_persona", str(project_config.persona))
    table.add_row("config_file_auto_handoff", str(project_config.auto_handoff))
    table.add_row("config_file_memory_amh_store", str(project_config.memory_amh_store))
    table.add_row("config_file_memory_amh_path", str(project_config.memory_amh_path))

    if latest_probe_expires:
        table.add_row("最新 probe entry 過期時間 (ACA)", latest_probe_expires)
    if latest_probe_audit != "N/A":
        table.add_row("最新 probe audit (ACA)", latest_probe_audit)
    if latest_probe_gov:
        table.add_row("最新 probe governance record (ACA)", latest_probe_gov)
    if latest_probe_gov_audit_full is not None:
        evs = latest_probe_gov_audit_full or []
        # Show COMPLETE list (no artificial cap) per "完整 audit 事件列表" request.
        # Keep per-event truncation for readability; append explicit 「全部事件」 + 捲動提示.
        formatted = []
        for i, e in enumerate(evs, 1):
            s = str(e).replace("\n", " | ")[:120]
            formatted.append(f"{i}. {s}")
        events_str = "\n".join(formatted) or "(none)"
        events_str += "\n（已列出全部事件；長列表請向上捲動查看；完整原始 audit 可經 /doctor 或 memory_audit 取得）"
        table.add_row("最新 probe gov audit events (ACA, 完整列表)", events_str)

    # MT22 後：只顯示新多任務清單
    current_tasks = load_tasks(settings.workspace)
    if current_tasks:
        summary = format_task_list_summary(current_tasks, max_active=5)
        table.add_row("tasks (multi)", summary[:400] if summary else "(none)")
    else:
        table.add_row("tasks", "(none)")

    console.print(table)

    # Add safety posture explanation (vision alignment, consistent with doctor/status)
    ap = approval_policy.mode.value
    meaning = {
        "auto": "YELLOW 操作會**自動執行**（較大膽，適合熟悉後使用）",
        "ask": "YELLOW 操作會**詢問確認**（平衡模式，建議新手使用）",
        "off": "YELLOW 操作會**被拒絕**（最保守）",
    }.get(ap, ap)

    console.print()
    console.print(f"[bold cyan]目前核准策略[/bold cyan]: {ap} → {meaning}")
    console.print(
        "[dim]安全原則：GREEN 永遠自動允許 ｜ YELLOW 依上方策略 ｜ "
        "RED 永遠受保護。你永遠可以透過 /approval 即時調整。[/dim]"
    )


def config_payload(
    settings: Settings,
    *,
    namespace: str,
    mode: str,
    approval: str,
) -> dict[str, object]:
    project_config = load_project_config(settings.workspace)
    return {
        "schema": "agentx.config.v1",
        "model": settings.model,
        "ollama_url": settings.ollama_url,
        "ollama_timeout": settings.ollama_timeout,
        "memory_backend": settings.memory_backend,
        "memory_amh_store": settings.memory_amh_store,
        "memory_amh_path": settings.memory_amh_path,
        "memory_hall_url": settings.memory_hall_url,
        "memory_hall_token": "set" if settings.memory_hall_token else "missing",
        "max_steps": settings.max_steps,
        "context_limit_tokens": settings.context_limit_tokens,
        "auto_handoff": settings.auto_handoff,
        "persona": settings.persona,
        "workspace": str(settings.workspace),
        "namespace": namespace,
        "mode": mode,
        "approval": approval,
        "learning_enabled": settings.learning_enabled,
        "project_config": {
            "model": project_config.model,
            "namespace": project_config.namespace,
            "mode": project_config.mode,
            "approval": project_config.approval,
            "persona": project_config.persona,
            "auto_handoff": project_config.auto_handoff,
            "memory_amh_store": project_config.memory_amh_store,
            "memory_amh_path": project_config.memory_amh_path,
        },
    }


def print_config_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="config",
        )
        return
    table = Table(title="agentX config", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key, value in payload.items():
        if key == "schema":
            continue
        table.add_row(key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value))
    console.print(table)


def _parse_git_branch_status(branch_line: str) -> dict[str, object]:
    if not branch_line.startswith("## "):
        return {
            "branch": None,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "initial": False,
        }

    head = branch_line.removeprefix("## ").strip()
    meta = ""
    if " [" in head and head.endswith("]"):
        head, meta = head.rsplit(" [", 1)
        meta = meta.rstrip("]")

    initial_prefix = "No commits yet on "
    initial = head.startswith(initial_prefix)
    detached = head.startswith("HEAD ") or head == "HEAD"
    branch = head.removeprefix(initial_prefix) if initial else head
    upstream = None
    if "..." in branch:
        branch, upstream = branch.split("...", 1)

    ahead = 0
    behind = 0
    if meta:
        for item in [part.strip() for part in meta.split(",")]:
            if item.startswith("ahead "):
                ahead = int(item.removeprefix("ahead ").strip() or "0")
            elif item.startswith("behind "):
                behind = int(item.removeprefix("behind ").strip() or "0")

    return {
        "branch": branch or None,
        "upstream": upstream or None,
        "ahead": ahead,
        "behind": behind,
        "detached": detached,
        "initial": initial,
    }


def git_status_payload(workspace: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "branch": None,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "initial": False,
            "dirty": None,
            "changes_count": None,
            "changes": [],
            "detail": f"{type(exc).__name__}: {exc}",
        }

    output = (result.stdout or result.stderr or "").strip()
    lines = output.splitlines()
    branch_line = lines[0] if lines and lines[0].startswith("## ") else ""
    changes = lines[1:] if branch_line else lines
    parsed = _parse_git_branch_status(branch_line)
    return {
        "ok": result.returncode == 0,
        **parsed,
        "dirty": bool(changes) if result.returncode == 0 else None,
        "changes_count": len(changes) if result.returncode == 0 else None,
        "changes": changes[:50],
        "detail": "" if result.returncode == 0 else output,
    }


def _git_read(
    workspace: Path,
    args: list[str],
    *,
    timeout: int = 10,
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _diff_relative_path(workspace: Path, path: str | None) -> str | None:
    if path in (None, ""):
        return None
    target = resolve_inside_workspace(workspace, path)
    return str(target.relative_to(workspace))


def _parse_diff_numstat(output: str) -> dict[str, dict[str, object]]:
    parsed: dict[str, dict[str, object]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, file_path = parts[0], parts[1], parts[2]
        binary = added_raw == "-" or deleted_raw == "-"
        added = None if binary else int(added_raw)
        deleted = None if binary else int(deleted_raw)
        parsed[file_path] = {
            "path": file_path,
            "added": added,
            "deleted": deleted,
            "binary": binary,
        }
    return parsed


def _parse_diff_name_status(output: str) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            files.append({"status": status, "path": parts[2], "old_path": parts[1]})
        elif status.startswith("C") and len(parts) >= 3:
            files.append({"status": status, "path": parts[2], "old_path": parts[1]})
        else:
            files.append({"status": status, "path": parts[1]})
    return files


def _parse_untracked_status(output: str) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.startswith("?? "):
            continue
        file_path = line[3:].strip()
        if file_path:
            files.append(
                {
                    "status": "??",
                    "path": file_path,
                    "added": None,
                    "deleted": None,
                    "binary": False,
                }
            )
    return files


def _diff_args(*, staged: bool, path: str | None) -> list[str]:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    return args


def diff_payload(
    settings: Settings,
    *,
    path: str | None = None,
    staged: bool = False,
    include_patch: bool = False,
    max_patch_chars: int = 20000,
) -> dict[str, object]:
    workspace = settings.workspace
    relative_path = _diff_relative_path(workspace, path)
    try:
        repo_code, repo_stdout, repo_stderr = _git_read(workspace, ["rev-parse", "--is-inside-work-tree"])
    except Exception as exc:
        return {
            "schema": "agentx.diff.v1",
            "workspace": str(workspace),
            "path": relative_path,
            "staged": staged,
            "ok": False,
            "is_git_repo": False,
            "dirty": None,
            "file_count": 0,
            "insertions": 0,
            "deletions": 0,
            "binary_count": 0,
            "untracked_count": 0,
            "files": [],
            "stat": "",
            "patch_included": include_patch,
            "patch": None,
            "patch_truncated": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    is_git_repo = repo_code == 0 and repo_stdout.strip() == "true"
    if not is_git_repo:
        detail = (repo_stderr or repo_stdout).strip()
        return {
            "schema": "agentx.diff.v1",
            "workspace": str(workspace),
            "path": relative_path,
            "staged": staged,
            "ok": False,
            "is_git_repo": False,
            "dirty": None,
            "file_count": 0,
            "insertions": 0,
            "deletions": 0,
            "binary_count": 0,
            "untracked_count": 0,
            "files": [],
            "stat": "",
            "patch_included": include_patch,
            "patch": None,
            "patch_truncated": False,
            "detail": detail or "not a git repository",
        }

    base_args = _diff_args(staged=staged, path=relative_path)
    stat_code, stat_stdout, stat_stderr = _git_read(workspace, [*base_args, "--stat"])
    numstat_code, numstat_stdout, numstat_stderr = _git_read(workspace, [*base_args, "--numstat"])
    status_code, status_stdout, status_stderr = _git_read(workspace, [*base_args, "--name-status"])
    untracked_code = 0
    untracked_stdout = ""
    untracked_stderr = ""
    if not staged:
        status_args = ["status", "--porcelain", "--untracked-files=all"]
        if relative_path:
            status_args.extend(["--", relative_path])
        untracked_code, untracked_stdout, untracked_stderr = _git_read(workspace, status_args)
    ok = stat_code == 0 and numstat_code == 0 and status_code == 0
    ok = ok and (staged or untracked_code == 0)

    numstat = _parse_diff_numstat(numstat_stdout if numstat_code == 0 else "")
    files = []
    for item in _parse_diff_name_status(status_stdout if status_code == 0 else ""):
        file_path = str(item["path"])
        stats = numstat.get(file_path, {})
        files.append(
            {
                **item,
                "added": stats.get("added"),
                "deleted": stats.get("deleted"),
                "binary": bool(stats.get("binary", False)),
            }
        )
    existing_paths = {str(item.get("path")) for item in files}
    untracked_files = [
        item
        for item in _parse_untracked_status(untracked_stdout if untracked_code == 0 else "")
        if str(item.get("path")) not in existing_paths
    ]
    files.extend(untracked_files)

    insertions = sum(int(item["added"]) for item in files if isinstance(item.get("added"), int))
    deletions = sum(int(item["deleted"]) for item in files if isinstance(item.get("deleted"), int))
    binary_count = sum(1 for item in files if item.get("binary") is True)
    untracked_count = len(untracked_files)
    patch_text = None
    patch_truncated = False
    patch_detail = ""
    if include_patch:
        patch_code, patch_stdout, patch_stderr = _git_read(workspace, base_args, timeout=20)
        ok = ok and patch_code == 0
        patch_text = patch_stdout[:max_patch_chars]
        patch_truncated = len(patch_stdout) > max_patch_chars
        patch_detail = patch_stderr.strip() if patch_code != 0 else ""

    details = [
        detail.strip()
        for detail in (stat_stderr, numstat_stderr, status_stderr, patch_detail)
        if detail.strip()
    ]
    if untracked_stderr.strip():
        details.append(untracked_stderr.strip())
    return {
        "schema": "agentx.diff.v1",
        "workspace": str(workspace),
        "path": relative_path,
        "staged": staged,
        "ok": ok,
        "is_git_repo": True,
        "dirty": bool(files),
        "file_count": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "binary_count": binary_count,
        "untracked_count": untracked_count,
        "files": files,
        "stat": stat_stdout if stat_code == 0 else "",
        "patch_included": include_patch,
        "patch": patch_text,
        "patch_truncated": patch_truncated,
        "detail": "\n".join(details),
    }


def _git_apply_read(
    workspace: Path,
    args: list[str],
    *,
    patch: str,
    timeout: int = 20,
) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "apply", *args, "-"],
        cwd=workspace,
        input=patch,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _patch_check_relative_path(workspace: Path, patch_file: str) -> tuple[Path | None, str, str]:
    try:
        target = resolve_inside_workspace(workspace, patch_file)
    except ValueError as exc:
        return None, patch_file, str(exc)
    try:
        relative = str(target.relative_to(workspace))
    except ValueError:
        relative = patch_file
    return target, relative, ""


def patch_check_payload(
    settings: Settings,
    *,
    patch_file: str,
    timeout: int = 20,
) -> dict[str, object]:
    workspace = settings.workspace
    patch_path, relative_patch, path_error = _patch_check_relative_path(workspace, patch_file)
    blockers: list[str] = []
    warnings: list[str] = []
    details: list[str] = []
    patch_text = ""

    if path_error:
        blockers.append("patch_file_escapes_workspace")
        details.append(path_error)
    elif patch_path is None or not patch_path.is_file():
        blockers.append("patch_file_not_found")
        details.append(f"patch file not found: {patch_file}")
    else:
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
        if not patch_text.strip():
            blockers.append("empty_patch")

    parsed_paths = patch_write_paths(patch_text) if patch_text else set()
    name_only_paths: set[str] = set()
    numstat: dict[str, dict[str, object]] = {}
    apply_check = {
        "command": "git apply --check -",
        "ok": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    if patch_text:
        try:
            check_code, check_stdout, check_stderr = _git_apply_read(
                workspace,
                ["--check"],
                patch=patch_text,
                timeout=timeout,
            )
            apply_check = {
                "command": "git apply --check -",
                "ok": check_code == 0,
                "exit_code": check_code,
                "stdout": check_stdout,
                "stderr": check_stderr,
            }
            if check_code != 0:
                blockers.append("git_apply_check_failed")
                details.append((check_stderr or check_stdout).strip())
        except subprocess.TimeoutExpired:
            blockers.append("git_apply_check_timeout")
            apply_check = {
                "command": "git apply --check -",
                "ok": False,
                "exit_code": 124,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
            }
            details.append(f"git apply --check timed out after {timeout}s")

        for args, collector in (
            (["--name-only"], name_only_paths),
        ):
            try:
                code, stdout, _stderr = _git_apply_read(workspace, args, patch=patch_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                warnings.append("git_apply_name_only_timeout")
                continue
            if code == 0:
                for line in stdout.splitlines():
                    path = line.strip()
                    if path and path != "/dev/null":
                        collector.add(path)

        try:
            numstat_code, numstat_stdout, _numstat_stderr = _git_apply_read(
                workspace,
                ["--numstat"],
                patch=patch_text,
                timeout=timeout,
            )
            if numstat_code == 0:
                numstat = _parse_diff_numstat(numstat_stdout)
        except subprocess.TimeoutExpired:
            warnings.append("git_apply_numstat_timeout")

    touched_paths = sorted(path for path in {*parsed_paths, *name_only_paths} if path and path != "/dev/null")
    files: list[dict[str, object]] = []
    unsafe_paths: list[str] = []
    for path in touched_paths:
        stats = numstat.get(path, {})
        safe = True
        safe_detail = ""
        try:
            ensure_safe_write_path(workspace, resolve_inside_workspace(workspace, path))
        except ValueError as exc:
            safe = False
            safe_detail = str(exc)
            unsafe_paths.append(path)
        files.append(
            {
                "path": path,
                "added": stats.get("added"),
                "deleted": stats.get("deleted"),
                "binary": bool(stats.get("binary", False)),
                "safe": safe,
                "detail": safe_detail,
                "source": sorted(
                    source
                    for source, paths in (("parsed", parsed_paths), ("git", name_only_paths))
                    if path in paths
                ),
            }
        )
    if unsafe_paths:
        blockers.append("unsafe_patch_paths")
        details.extend(f"{path}: unsafe patch target" for path in unsafe_paths)
    if patch_text and not touched_paths:
        warnings.append("no_touched_paths_detected")

    ok = not blockers
    next_commands = ["agentx diff --json"]
    if ok:
        next_commands.append(f"/apply {relative_patch}")
        recommended_command = f"/apply {relative_patch}"
        recommended_kind = "apply_patch"
        recommended_risk = "YELLOW"
    else:
        next_commands.append("fix patch blockers, then rerun agentx patch-check PATCH --json")
        recommended_command = "fix patch blockers, then rerun agentx patch-check PATCH --json"
        recommended_kind = "fix_patch_blockers"
        recommended_risk = "UNKNOWN"

    return {
        "schema": "agentx.patch_check.v1",
        "workspace": str(workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "patch_file": relative_patch,
        "ok": ok,
        "blockers": blockers,
        "warnings": warnings,
        "apply_check": apply_check,
        "safe_paths_ok": not unsafe_paths,
        "file_count": len(files),
        "files": files,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "next_commands": next_commands,
        "detail": "\n".join(detail for detail in details if detail),
    }


def patch_check_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1


def print_patch_check_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="patch_check",
        )
        return

    table = Table(title="agentX patch check", show_header=True, header_style="bold")
    table.add_column("Safe", style="cyan")
    table.add_column("Path")
    table.add_column("+", justify="right")
    table.add_column("-", justify="right")
    for item in payload["files"]:  # type: ignore[index]
        row = dict(item)
        table.add_row(
            "yes" if row.get("safe") is True else "no",
            str(row.get("path", "")),
            "-" if row.get("added") is None else str(row.get("added")),
            "-" if row.get("deleted") is None else str(row.get("deleted")),
        )
    console.print(table)
    console.print(
        f"[dim]ok={payload['ok']} files={payload['file_count']} "
        f"blockers={','.join(str(item) for item in payload['blockers']) or '-'} "
        f"recommended={payload.get('recommended_command') or '-'}[/dim]"
    )


def print_diff_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="diff",
        )
        return

    table = Table(title="agentX diff", show_header=True, header_style="bold")
    table.add_column("Status", style="cyan")
    table.add_column("Path")
    table.add_column("+", justify="right")
    table.add_column("-", justify="right")
    for item in payload["files"]:  # type: ignore[index]
        row = dict(item)
        table.add_row(
            str(row.get("status", "")),
            str(row.get("path", "")),
            "-" if row.get("added") is None else str(row.get("added")),
            "-" if row.get("deleted") is None else str(row.get("deleted")),
        )
    console.print(table)
    console.print(
        f"[dim]ok={payload['ok']} staged={payload['staged']} files={payload['file_count']} "
        f"insertions={payload['insertions']} deletions={payload['deletions']} "
        f"untracked={payload['untracked_count']}[/dim]"
    )
    if payload.get("stat"):
        console.print(str(payload["stat"]).rstrip())


def task_status_payload(workspace: Path) -> dict[str, object]:
    tasks = load_tasks(workspace)
    active = [task for task in tasks if task.get("status") in {"in_progress", "pending", "blocked"}]
    return {
        "count": len(tasks),
        "by_status": _headless_task_counts(tasks),
        "active": [
            {
                "id": task.get("id"),
                "description": task.get("description"),
                "status": task.get("status"),
            }
            for task in active[:5]
        ],
    }


TASK_STATUS_FILTERS = {"all", "active", "pending", "in_progress", "done", "blocked"}


def tasks_payload(settings: Settings, *, status_filter: str = "all") -> dict[str, object]:
    """Return the complete project task list for headless automation."""
    normalized_filter = status_filter.strip().lower()
    if normalized_filter not in TASK_STATUS_FILTERS:
        allowed = ", ".join(sorted(TASK_STATUS_FILTERS))
        raise typer.BadParameter(f"status must be one of: {allowed}")

    all_tasks = load_tasks(settings.workspace)
    if normalized_filter == "all":
        filtered_tasks = all_tasks
    elif normalized_filter == "active":
        filtered_tasks = [
            task
            for task in all_tasks
            if task.get("status") in {"pending", "in_progress", "blocked"}
        ]
    else:
        filtered_tasks = [task for task in all_tasks if task.get("status") == normalized_filter]

    return {
        "schema": "agentx.tasks.v1",
        "workspace": str(settings.workspace),
        "status_filter": normalized_filter,
        "count": len(filtered_tasks),
        "total_count": len(all_tasks),
        "by_status": _headless_task_counts(all_tasks),
        "tasks": filtered_tasks,
        "summary": format_task_list_summary(all_tasks),
    }


def print_tasks_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="tasks",
        )
        return

    table = Table(title="agentX tasks", show_header=True, header_style="bold")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Status")
    table.add_column("Description")
    table.add_column("Notes")
    for task in payload["tasks"]:  # type: ignore[index]
        row = dict(task)
        table.add_row(
            str(row.get("id", "")),
            str(row.get("status", "")),
            str(row.get("description", "")),
            str(row.get("notes", "")),
        )
    console.print(table)
    console.print(
        "[dim]"
        f"count={payload['count']} total={payload['total_count']} "
        f"by_status={json.dumps(payload['by_status'], ensure_ascii=False)}"
        "[/dim]"
    )


def default_verify_commands(workspace: Path) -> list[list[str]]:
    files = {path.name for path in workspace.iterdir()}
    commands: list[list[str]] = []
    if "pyproject.toml" in files:
        commands.extend(
            [
                ["uv", "run", "ruff", "check", "."],
                ["uv", "run", "pytest", "-q"],
            ]
        )
    if "package.json" in files:
        commands.append(["npm", "test"])
    return commands


def verify_payload_from_checks(
    checks: list[dict[str, object]],
    *,
    settings: Settings,
) -> dict[str, object]:
    ok = bool(checks) and all(bool(check.get("ok")) for check in checks)
    if ok:
        recommended_command = "agentx review --json"
        recommended_kind = "review"
        recommended_risk = "GREEN"
    else:
        recommended_command = "fix verification failures, then rerun agentx verify --json --fail-on-error"
        recommended_kind = "fix_verify"
        recommended_risk = "UNKNOWN"
    return {
        "schema": "agentx.verify.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "count": len(checks),
        "checks": checks,
    }


def verify_payload(
    settings: Settings,
    *,
    timeout: int = 120,
    output_limit: int = 12000,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    commands = default_verify_commands(settings.workspace)
    if not commands:
        return verify_payload_from_checks(
            [
                {
                    "command": "",
                    "argv": [],
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "output": "no default verification commands detected",
                }
            ],
            settings=settings,
        )

    for command in commands:
        command_text = shlex.join(command)
        try:
            completed = subprocess.run(
                command,
                cwd=settings.workspace,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            stdout = (completed.stdout or "")[:output_limit]
            stderr = (completed.stderr or "")[:output_limit]
            output = (completed.stdout or completed.stderr or "")[:output_limit]
            check = {
                "command": command_text,
                "argv": command,
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            check = {
                "command": command_text,
                "argv": command,
                "ok": False,
                "exit_code": 124,
                "stdout": stdout[:output_limit],
                "stderr": stderr[:output_limit],
                "output": f"timeout after {timeout}s",
            }
        checks.append(check)
        if not check["ok"]:
            break

    return verify_payload_from_checks(checks, settings=settings)


def verify_exit_code(payload: dict[str, object], *, fail_on_error: bool = False) -> int:
    if not fail_on_error:
        return 0
    return 0 if payload.get("ok") is True else 1


def review_payload(
    settings: Settings,
    *,
    timeout: int = 120,
    run_verify: bool = True,
) -> dict[str, object]:
    diff = diff_payload(settings)
    verify = verify_payload(settings, timeout=timeout) if run_verify else None
    blockers: list[str] = []
    warnings: list[str] = []

    if diff.get("ok") is not True:
        blockers.append("diff_unavailable")
    elif diff.get("dirty") is not True:
        blockers.append("no_changes")

    if verify is None:
        warnings.append("verify_skipped")
    elif verify.get("ok") is not True:
        blockers.append("verify_failed")

    if diff.get("untracked_count", 0):
        warnings.append("has_untracked_files")

    commit_ready = not blockers and verify is not None
    next_commands = ["agentx diff --json"]
    if verify is None:
        next_commands.append("agentx verify --json --fail-on-error")
    if commit_ready:
        next_commands.append("/commit 中文訊息")
        recommended_command = "/commit 中文訊息"
        recommended_kind = "commit"
        recommended_risk = "YELLOW"
    elif blockers:
        next_commands.append("fix blockers, then rerun agentx review --json")
        recommended_command = "fix blockers, then rerun agentx review --json"
        recommended_kind = "fix_blockers"
        recommended_risk = "UNKNOWN"
    elif verify is None:
        recommended_command = "agentx verify --json --fail-on-error"
        recommended_kind = "verify"
        recommended_risk = "GREEN"
    else:
        next_commands.append("agentx review --json")
        recommended_command = "agentx review --json"
        recommended_kind = "review"
        recommended_risk = "GREEN"

    return {
        "schema": "agentx.review.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not blockers,
        "commit_ready": commit_ready,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "blockers": blockers,
        "warnings": warnings,
        "diff": diff,
        "verify": verify,
        "next_commands": next_commands,
    }


def print_review_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="review",
        )
        return

    diff = dict(payload["diff"])  # type: ignore[arg-type]
    verify = payload.get("verify")
    verify_ok = None if verify is None else dict(verify).get("ok")  # type: ignore[arg-type]
    table = Table(title="agentX review gate", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload["ok"]))
    table.add_row("commit_ready", str(payload["commit_ready"]))
    table.add_row(
        "diff",
        f"dirty={diff.get('dirty')} files={diff.get('file_count')} "
        f"insertions={diff.get('insertions')} deletions={diff.get('deletions')} "
        f"untracked={diff.get('untracked_count')}",
    )
    table.add_row("verify", "skipped" if verify is None else f"ok={verify_ok}")
    table.add_row("blockers", ", ".join(str(item) for item in payload["blockers"]) or "-")
    table.add_row("warnings", ", ".join(str(item) for item in payload["warnings"]) or "-")
    console.print(table)


def review_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1


def commit_plan_payload(
    settings: Settings,
    *,
    message: str | None = None,
    timeout: int = 120,
    run_verify: bool = True,
) -> dict[str, object]:
    plan = build_commit_plan(settings.workspace)
    review = review_payload(settings, timeout=timeout, run_verify=run_verify)
    commit_message = (message or "").strip()
    blockers = [str(item) for item in review.get("blockers", [])]
    warnings = [str(item) for item in review.get("warnings", [])]
    if not commit_message:
        blockers.append("missing_commit_message")
    review_commit_ready = review.get("commit_ready") is True
    ready_to_commit = not blockers and review_commit_ready and bool(plan.files)
    next_commands = ["agentx diff --json"]
    if not commit_message:
        next_commands.append("agentx commit-plan --message '中文 commit 訊息' --json")
    if ready_to_commit:
        next_commands.append(f"/commit {commit_message}")
        recommended_command = f"/commit {commit_message}"
        recommended_kind = "commit"
        recommended_risk = "YELLOW"
    elif blockers:
        next_commands.append("fix blockers, then rerun agentx commit-plan --message '中文 commit 訊息' --json")
        recommended_command = "fix blockers, then rerun agentx commit-plan --message '中文 commit 訊息' --json"
        recommended_kind = "fix_blockers"
        recommended_risk = "UNKNOWN"
    elif not review_commit_ready:
        next_commands.append("agentx review --json --fail-on-blocker")
        recommended_command = "agentx review --json --fail-on-blocker"
        recommended_kind = "review"
        recommended_risk = "GREEN"
    else:
        recommended_command = "agentx commit-plan --message '中文 commit 訊息' --json"
        recommended_kind = "commit_plan"
        recommended_risk = "GREEN"

    return {
        "schema": "agentx.commit_plan.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not blockers,
        "ready_to_commit": ready_to_commit,
        "commit_message": commit_message or None,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "blockers": blockers,
        "warnings": warnings,
        "status": plan.status,
        "diff_stat": plan.diff_stat,
        "files_to_stage": plan.files,
        "file_count": len(plan.files),
        "review": review,
        "next_commands": next_commands,
    }


def print_commit_plan_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="commit_plan",
        )
        return

    table = Table(title="agentX commit plan", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload["ok"]))
    table.add_row("ready_to_commit", str(payload["ready_to_commit"]))
    table.add_row("commit_message", str(payload.get("commit_message") or "-"))
    table.add_row("files", str(payload["file_count"]))
    table.add_row("blockers", ", ".join(str(item) for item in payload["blockers"]) or "-")
    table.add_row("warnings", ", ".join(str(item) for item in payload["warnings"]) or "-")
    console.print(table)
    for path in payload["files_to_stage"]:  # type: ignore[index]
        console.print(f"- {path}")


def commit_plan_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1


def gate_payload(
    settings: Settings,
    *,
    timeout: int = 120,
    run_verify: bool = True,
    run_doctor: bool = True,
    run_approvals: bool = True,
    approvals_limit: int = 20,
) -> dict[str, object]:
    review = review_payload(settings, timeout=timeout, run_verify=run_verify)
    doctor = doctor_payload(settings, live_probes=False) if run_doctor else None
    approvals = approvals_payload(settings, session="latest", limit=approvals_limit) if run_approvals else None
    blockers = [str(item) for item in review.get("blockers", [])]
    warnings = [str(item) for item in review.get("warnings", [])]

    if doctor is None:
        warnings.append("doctor_skipped")
    elif doctor.get("ok") is not True:
        blockers.append("doctor_failed")

    if approvals is None:
        warnings.append("approvals_skipped")
    elif approvals.get("ok") is not True:
        warnings.append("approvals_unavailable")
    elif int(approvals.get("denied_count", 0) or 0) > 0:
        blockers.append("approval_denied")

    commit_ready = review.get("commit_ready") is True and not blockers
    next_commands = [
        "agentx inspect --json",
        "agentx review --json --fail-on-blocker",
        "agentx doctor --static --json --fail-on-error",
        "agentx approvals latest --denied --json --fail-on-denied",
    ]
    if commit_ready:
        next_commands.append("agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker")
        recommended_command = "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker"
        recommended_kind = "commit_plan"
        recommended_risk = "GREEN"
    elif blockers:
        next_commands.append("fix blockers, then rerun agentx gate --json --fail-on-blocker")
        recommended_command = "fix blockers, then rerun agentx gate --json --fail-on-blocker"
        recommended_kind = "fix_blockers"
        recommended_risk = "UNKNOWN"
    else:
        next_commands.append("agentx gate --json")
        recommended_command = "agentx gate --json"
        recommended_kind = "gate"
        recommended_risk = "GREEN"

    return {
        "schema": "agentx.gate.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not blockers,
        "commit_ready": commit_ready,
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "blockers": blockers,
        "warnings": warnings,
        "review": review,
        "doctor": doctor,
        "approvals": approvals,
        "next_commands": next_commands,
    }


def print_gate_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="gate",
        )
        return

    review = dict(payload["review"])  # type: ignore[arg-type]
    doctor = payload.get("doctor")
    approvals = payload.get("approvals")
    table = Table(title="agentX gate", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload["ok"]))
    table.add_row("commit_ready", str(payload["commit_ready"]))
    table.add_row("review", f"ok={review.get('ok')} commit_ready={review.get('commit_ready')}")
    table.add_row("doctor", "skipped" if doctor is None else f"ok={dict(doctor).get('ok')}")  # type: ignore[arg-type]
    table.add_row(
        "approvals",
        "skipped"
        if approvals is None
        else f"ok={dict(approvals).get('ok')} denied={dict(approvals).get('denied_count')}",  # type: ignore[arg-type]
    )
    table.add_row("blockers", ", ".join(str(item) for item in payload["blockers"]) or "-")
    table.add_row("warnings", ", ".join(str(item) for item in payload["warnings"]) or "-")
    console.print(table)


def gate_exit_code(payload: dict[str, object], *, fail_on_blocker: bool = False) -> int:
    if not fail_on_blocker:
        return 0
    return 0 if payload.get("ok") is True else 1


def _next_task_reason(base: str, task: dict[str, object] | None) -> str:
    if not task:
        return base
    task_id = task.get("id")
    description = str(task.get("description") or "").strip()
    status = str(task.get("status") or "").strip()
    task_ref = f"#{task_id}" if task_id is not None else "active task"
    details = [task_ref]
    if status:
        details.append(status)
    if description:
        details.append(description[:80])
    return f"{base}; primary={': '.join(details)}"


def next_payload(
    settings: Settings,
    *,
    artifacts_root: str = ".agentx/runs",
    artifacts_limit: int = 5,
    approvals_limit: int = 20,
) -> dict[str, object]:
    diff = diff_payload(settings)
    tasks = tasks_payload(settings, status_filter="active")
    artifacts = artifacts_payload(settings, root=artifacts_root, limit=artifacts_limit)
    approvals = approvals_payload(settings, session="latest", limit=approvals_limit, denied_only=True)

    recommendations: list[dict[str, object]] = []
    denied_count = int(approvals.get("denied_count", 0) or 0) if approvals.get("ok") is True else 0
    dirty = diff.get("dirty") is True
    active_task_count = int(tasks.get("count", 0) or 0)
    active_task_items = [dict(task) for task in tasks.get("tasks", [])] if isinstance(tasks.get("tasks"), list) else []
    active_task_ids = [task.get("id") for task in active_task_items if task.get("id") is not None]
    primary_active_task = active_task_items[0] if active_task_items else None
    artifact_items = list(artifacts.get("artifacts", [])) if artifacts.get("ok") is True else []
    latest_artifact = dict(artifact_items[0]) if artifact_items else None
    latest_needs_handoff = bool(latest_artifact and latest_artifact.get("needs_handoff") is True)

    if denied_count > 0:
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "approval_audit",
                "command": "agentx approvals latest --denied --json --fail-on-denied",
                "reason": "latest transcript has denied approval receipts",
                "risk": "GREEN",
            }
        )
    if dirty:
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "gate",
                "command": "agentx gate --json --fail-on-blocker",
                "reason": "workspace has git changes; run aggregate gate before commit or handoff",
                "risk": "GREEN",
            }
        )
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "commit_plan",
                "command": "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker",
                "reason": "after the gate passes, preview explicit files and commit message",
                "risk": "GREEN",
            }
        )
    if latest_artifact is not None and latest_needs_handoff:
        artifact_path = str(latest_artifact.get("relative_path") or latest_artifact.get("path") or artifacts_root)
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "handoff_resume",
                "command": f"agentx handoff-resume {shlex.quote(artifact_path)} --dry-run",
                "reason": "latest artifact reports needs_handoff=true",
                "risk": "GREEN",
            }
        )
    if not dirty and active_task_count > 0:
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "task_resume",
                "command": "agentx tasks active --json",
                "reason": _next_task_reason("active tasks exist and the workspace is clean", primary_active_task),
                "risk": "GREEN",
            }
        )
        recommendations.append(
            {
                "rank": len(recommendations) + 1,
                "kind": "headless_continue",
                "command": "agentx -p '繼續目前 active task' --agent --json",
                "reason": _next_task_reason("continue active task work from current repo state", primary_active_task),
                "risk": "YELLOW",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "rank": 1,
                "kind": "inspect",
                "command": "agentx inspect --json",
                "reason": "workspace is clean and no active runner handoff was detected",
                "risk": "GREEN",
            }
        )
    for recommendation in recommendations:
        recommendation["command_plan"] = command_plan_payload(settings, str(recommendation["command"]))

    return {
        "schema": "agentx.next.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": True,
        "recommended_command": recommendations[0]["command"] if recommendations else None,
        "recommended_kind": recommendations[0]["kind"] if recommendations else None,
        "recommended_risk": recommendations[0]["risk"] if recommendations else None,
        "recommendations": recommendations,
        "signals": {
            "dirty": dirty,
            "diff_ok": diff.get("ok") is True,
            "active_task_count": active_task_count,
            "active_task_ids": active_task_ids,
            "primary_active_task": primary_active_task,
            "artifact_count": artifacts.get("count", 0),
            "latest_artifact_needs_handoff": latest_needs_handoff,
            "denied_approval_count": denied_count,
            "approvals_available": approvals.get("ok") is True,
        },
        "diff": diff,
        "tasks": tasks,
        "artifacts": artifacts,
        "approvals": approvals,
    }


def print_next_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="next",
        )
        return

    table = Table(title="agentX next", show_header=True, header_style="bold")
    table.add_column("Rank", style="cyan", justify="right")
    table.add_column("Kind")
    table.add_column("Command")
    table.add_column("Reason")
    for item in payload["recommendations"]:  # type: ignore[index]
        row = dict(item)
        table.add_row(
            str(row.get("rank", "")),
            str(row.get("kind", "")),
            str(row.get("command", "")),
            str(row.get("reason", "")),
        )
    console.print(table)
    console.print(f"[dim]recommended={payload.get('recommended_command') or '-'}[/dim]")


def print_verify_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="verify",
        )
        return

    table = Table(title="agentX verify", show_header=True, header_style="bold")
    table.add_column("Command", style="cyan")
    table.add_column("Exit", justify="right")
    table.add_column("OK")
    for check in payload["checks"]:  # type: ignore[index]
        row = dict(check)
        table.add_row(
            str(row.get("command", "")) or "-",
            str(row.get("exit_code", "-")),
            "yes" if row.get("ok") is True else "no",
        )
    console.print(table)
    console.print(
        f"[dim]ok={payload['ok']} count={payload['count']} "
        f"recommended={payload.get('recommended_command') or '-'}[/dim]"
    )


def inspect_payload(
    settings: Settings,
    *,
    namespace: str,
    mode: str,
    approval: str,
    sessions_limit: int = 5,
    approvals_limit: int = 20,
) -> dict[str, object]:
    verify_commands = [
        {"command": shlex.join(command), "argv": command}
        for command in default_verify_commands(settings.workspace)
    ]
    verify_command_plans = [
        command_plan_payload(settings, str(item["command"]))
        for item in verify_commands
    ]
    artifacts = artifacts_payload(settings, root=".agentx/runs", limit=5)
    next_steps = next_payload(
        settings,
        artifacts_root=".agentx/runs",
        artifacts_limit=5,
        approvals_limit=approvals_limit,
    )
    next_signals = next_steps.get("signals", {})
    signals = dict(next_signals) if isinstance(next_signals, dict) else {}
    signals.update(
        {
            "verify_command_count": len(verify_commands),
            "verify_command_plan_count": len(verify_command_plans),
        }
    )
    return {
        "schema": "agentx.inspect.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": True,
        "live_probes": False,
        "recommended_command": next_steps.get("recommended_command"),
        "recommended_kind": next_steps.get("recommended_kind"),
        "recommended_risk": next_steps.get("recommended_risk"),
        "signals": signals,
        "status": status_payload(
            settings,
            namespace=namespace,
            mode=mode,
            approval=approval,
        ),
        "tasks": tasks_payload(settings, status_filter="active"),
        "sessions": sessions_payload(settings, limit=sessions_limit),
        "approvals": approvals_payload(settings, session="latest", limit=approvals_limit),
        "traces": traces_payload(settings, session="latest", limit=20),
        "diff": diff_payload(settings),
        "capabilities": capabilities_payload(),
        "artifacts": artifacts,
        "next": next_steps,
        "verify_commands": verify_commands,
        "verify_command_plans": verify_command_plans,
        "next_commands": [
            "agentx diff --json",
            "agentx gate --json --fail-on-blocker",
            "agentx review --json --fail-on-blocker",
            "agentx commit-plan --message '中文 commit 訊息' --json --fail-on-blocker",
            "agentx verify --json --fail-on-error",
            "agentx tasks active --json",
            "agentx approvals latest --denied --json --fail-on-denied",
            "agentx traces latest --json",
        ],
    }


def print_inspect_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="inspect",
        )
        return

    status = dict(payload["status"])  # type: ignore[arg-type]
    runtime = dict(status["runtime"])  # type: ignore[arg-type]
    git = dict(status["git"])  # type: ignore[arg-type]
    tasks = dict(payload["tasks"])  # type: ignore[arg-type]
    sessions = dict(payload["sessions"])  # type: ignore[arg-type]
    approvals = dict(payload["approvals"])  # type: ignore[arg-type]
    artifacts = dict(payload["artifacts"])  # type: ignore[arg-type]
    next_steps = dict(payload["next"])  # type: ignore[arg-type]
    table = Table(title="agentX inspect", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("ok", str(payload.get("ok")))
    table.add_row(
        "runtime",
        f"model={runtime.get('model')} mode={runtime.get('mode')} approval={runtime.get('approval')} "
        f"namespace={runtime.get('namespace')}",
    )
    table.add_row(
        "git",
        f"ok={git.get('ok')} dirty={git.get('dirty')} branch={git.get('branch')} "
        f"ahead={git.get('ahead')} behind={git.get('behind')}",
    )
    table.add_row(
        "tasks",
        f"active={tasks.get('count')} total={tasks.get('total_count')} "
        f"by_status={json.dumps(tasks.get('by_status'), ensure_ascii=False)}",
    )
    table.add_row("sessions", f"count={sessions.get('count')}")
    table.add_row(
        "approvals",
        f"ok={approvals.get('ok')} count={approvals.get('count')} denied={approvals.get('denied_count')}",
    )
    diff = dict(payload["diff"])  # type: ignore[arg-type]
    table.add_row(
        "diff",
        f"ok={diff.get('ok')} dirty={diff.get('dirty')} files={diff.get('file_count')} "
        f"insertions={diff.get('insertions')} deletions={diff.get('deletions')}",
    )
    table.add_row("artifacts", f"ok={artifacts.get('ok')} count={artifacts.get('count')}")
    table.add_row("next", str(next_steps.get("recommended_command") or "-"))
    table.add_row(
        "verify_commands",
        ", ".join(str(item["command"]) for item in payload["verify_commands"]) or "-",
    )
    table.add_row(
        "verify_command_plans",
        ", ".join(
            f"{item.get('command')}:{item.get('risk')}"
            for item in payload.get("verify_command_plans", [])  # type: ignore[union-attr]
            if isinstance(item, dict)
        )
        or "-",
    )
    console.print(table)


def status_payload(
    settings: Settings,
    *,
    namespace: str,
    mode: str,
    approval: str,
) -> dict[str, object]:
    config = config_payload(settings, namespace=namespace, mode=mode, approval=approval)
    return {
        "schema": "agentx.status.v1",
        "version": version_payload(),
        "workspace": str(settings.workspace),
        "runtime": {
            "model": config["model"],
            "namespace": namespace,
            "mode": mode,
            "approval": approval,
            "persona": config["persona"],
            "memory_backend": config["memory_backend"],
            "auto_handoff": config["auto_handoff"],
        },
        "git": git_status_payload(settings.workspace),
        "tasks": task_status_payload(settings.workspace),
        "config": config,
    }


def print_status_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="status",
        )
        return

    runtime = dict(payload["runtime"])  # type: ignore[arg-type]
    git = dict(payload["git"])  # type: ignore[arg-type]
    tasks = dict(payload["tasks"])  # type: ignore[arg-type]
    task_counts = tasks.get("by_status", {})
    table = Table(title="agentX status", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("version", json.dumps(payload["version"], ensure_ascii=False))
    table.add_row(
        "runtime",
        f"model={runtime.get('model')} mode={runtime.get('mode')} approval={runtime.get('approval')} "
        f"namespace={runtime.get('namespace')}",
    )
    table.add_row(
        "git",
        f"ok={git.get('ok')} branch={git.get('branch')} upstream={git.get('upstream')} "
        f"dirty={git.get('dirty')} ahead={git.get('ahead')} behind={git.get('behind')} "
        f"changes={git.get('changes_count')}",
    )
    table.add_row("tasks", f"count={tasks.get('count')} by_status={json.dumps(task_counts, ensure_ascii=False)}")
    console.print(table)


def doctor_payload_from_checks(
    checks: list[tuple[str, bool, str]],
    *,
    settings: Settings,
    live_probes: bool,
) -> dict[str, object]:
    normalized = [
        {
            "name": name,
            "ok": ok,
            "detail": detail,
        }
        for name, ok, detail in checks
    ]
    return {
        "schema": "agentx.doctor.v1",
        "workspace": str(settings.workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "live_probes": live_probes,
        "ok": all(item["ok"] for item in normalized),
        "checks": normalized,
    }


def doctor_payload(
    settings: Settings,
    *,
    memory: MemoryHallClient | NullMemoryClient | None = None,
    ollama: OllamaClient | None = None,
    live_probes: bool = True,
) -> dict[str, object]:
    if live_probes:
        if memory is None or ollama is None:
            raise ValueError("live doctor probes require memory and ollama clients")
        checks = run_doctor(settings, memory, ollama)
    else:
        checks = run_static_doctor(settings)
    return doctor_payload_from_checks(checks, settings=settings, live_probes=live_probes)


def print_doctor_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="doctor",
        )
        return

    table = Table(title="agentX doctor", show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("OK")
    table.add_column("Detail")
    for item in payload["checks"]:  # type: ignore[index]
        check = dict(item)
        table.add_row(str(check["name"]), "yes" if check["ok"] else "no", str(check["detail"]))
    console.print(table)


def doctor_exit_code(payload: dict[str, object], *, fail_on_error: bool = False) -> int:
    if not fail_on_error:
        return 0
    return 0 if payload.get("ok") is True else 1


def _collect_aca_probe_info(
    settings: Settings, memory: "MemoryHallClient | None"
) -> dict:
    """Collect live ACA probe/governance/audit signals for /status, /config and /doctor.

    This enables /status to also display the complete post-governance-record audit event list
    (with full events + 捲動提示), without duplicating collection logic.
    """
    info = {
        "client_type": "N/A",
        "latest_probe_expires": None,
        "latest_probe_audit": "N/A",
        "latest_probe_gov": None,
        "latest_probe_gov_audit_full": None,
    }
    if getattr(settings, "memory_backend", "memhall") != "amh" or memory is None:
        return info
    info["client_type"] = type(memory).__name__
    try:
        entries = memory.list_entries(
            namespace="project:agentX",
            entry_type="note",
            tags=["aca", "doctor", "probe"],
            limit=5,
        )
        probe_marker = None
        for e in entries or []:
            if isinstance(e, dict):
                e_str = str(e)
                if "aca-doctor-probe-write" in e_str and not probe_marker:
                    start = e_str.find("aca-doctor-probe-write:")
                    if start >= 0:
                        probe_marker = e_str[start : start + 50].split()[0]
                    info["latest_probe_expires"] = e.get("valid_until") or (e.get("metadata") or {}).get(
                        "valid_until"
                    )
                    if info["latest_probe_expires"] and probe_marker:
                        try:
                            events = memory.audit(probe_marker) if hasattr(memory, "audit") else []
                            info["latest_probe_audit"] = f"{len(events)} events"
                            if events:
                                info["latest_probe_audit"] += f" (first: {str(events[0])[:60]})"
                        except Exception:
                            info["latest_probe_audit"] = "audit error"
                # governance record (post probe write)
                if ("governance" in e_str or "probe_completed" in e_str or "probe 完成" in e_str) and probe_marker:
                    meta = e.get("metadata") or {}
                    evidence = meta.get("evidence_ids", [])
                    gov_type = meta.get("governance_type")
                    if evidence or gov_type:
                        info["latest_probe_gov"] = f"type={gov_type}, evidence_ids={evidence}"
                        try:
                            events = memory.audit(probe_marker) if hasattr(memory, "audit") else []
                            info["latest_probe_gov_audit_full"] = events
                        except Exception:
                            info["latest_probe_gov_audit_full"] = []
    except Exception:
        pass
    return info


def print_doctor(
    settings: Settings,
    memory: MemoryHallClient,
    ollama: OllamaClient,
    *,
    approval_mode: str | None = None,
    current_mode: str | None = None,
) -> None:
    """Enhanced doctor output that surfaces both technical health and product posture.

    This improvement helps close the gap on Image 05 (Safety as a visible strength)
    and Image 04 (Memory Hall as real continuity).
    """

    # === Technical health checks (original) ===
    tech_table = Table(title="agentX doctor — 技術健康檢查", show_header=True, header_style="bold")
    tech_table.add_column("Check", style="cyan")
    tech_table.add_column("OK")
    tech_table.add_column("Detail")
    for name, ok, detail in run_doctor(settings, memory, ollama):
        tech_table.add_row(name, "yes" if ok else "no", detail)
    console.print(tech_table)
    console.print()

    # === Product Posture Summary (new, vision-aligned) ===
    posture = Table(title="agentX 目前狀態與使用建議", show_header=False)
    posture.add_column("項目", style="bold cyan")
    posture.add_column("內容")

    mode_str = current_mode or "unknown"
    approval_str = approval_mode or "ask (預設)"
    approval_meaning = {
        "auto": "YELLOW 操作會自動執行（較大膽）",
        "ask": "YELLOW 操作會詢問確認（平衡）",
        "off": "YELLOW 操作受限（最保守）",
    }.get(approval_str.split()[0], "依設定")

    posture.add_row("目前模式", f"{mode_str}（chat = 純聊天，agent = 可使用工具）")
    posture.add_row("核准策略 (approval)", f"{approval_str} → {approval_meaning}")
    posture.add_row("安全邊界", "GREEN 自動允許 ｜ YELLOW 依策略 ｜ RED 永遠受保護（設計如此）")
    backend = getattr(settings, "memory_backend", "memhall")
    if backend == "amh":
        store = getattr(settings, "memory_amh_store", "json")
        probe_info = _collect_aca_probe_info(settings, memory)
        client = probe_info["client_type"] or "AmhClient"
        mh_text = f"跨 session 記憶與交接已啟用（/handoff /resume） | ACA amh backend (store={store}, client={client})"
        probe_exp = probe_info["latest_probe_expires"]
        if probe_exp:
            mh_text += f" | 最近 probe entry 過期時間: {probe_exp}"
        probe_audit = probe_info["latest_probe_audit"]
        if probe_audit and probe_audit != "N/A":
            mh_text += f" | probe audit: {probe_audit}"
        gov = probe_info["latest_probe_gov"]
        if gov:
            mh_text += f" | probe gov record: {gov}"
        gov_full = probe_info["latest_probe_gov_audit_full"]
        if gov_full is not None:
            mh_text += f" | gov audit events: {len(gov_full or [])} (完整列表見 /config 表格，含全部事件 + 捲動提示)"
        posture.add_row("Memory Hall", mh_text)
    else:
        posture.add_row("Memory Hall", "跨 session 記憶與交接已啟用（/handoff /resume）")
    posture.add_row("建議", "想更自主就輸入 /approval auto；想最安全就保持 ask 或 off")

    console.print(posture)
    console.print("[dim]這是 agentX 的「安全優先」設計 — 你始終是主人，agentX 是工具。[/dim]")


def run_commit_flow(settings: Settings, tools: ToolRegistry, message: str | None) -> str:
    plan = build_commit_plan(settings.workspace)
    if not plan.files:
        return "No changes to commit."

    tests = tools.run("run_tests", {})
    if not tests.ok or "exit=1" in tests.content:
        return "Tests failed; aborting commit.\n\n" + tests.content

    commit_message = message or typer.prompt("Commit message 中文").strip()
    if not commit_message:
        return "Commit message is required."

    console.print("git status:")
    print_raw(plan.status)
    console.print("git diff --stat:")
    print_raw(plan.diff_stat or "(no tracked diff stat; maybe untracked files only)")
    console.print("files to stage one by one:")
    for path in plan.files:
        console.print(f"- {path}")
    console.print("tests:")
    print_raw(tests.content)

    if typer.prompt("Commit and push? type yes").strip().lower() != "yes":
        return "commit cancelled"

    return commit_and_push(settings.workspace, plan.files, commit_message)


@dataclass(frozen=True)
class HeadlessRunResult:
    output: str
    termination: str = "unknown"
    failing_tools: tuple[str, ...] = ()
    stats: dict[str, object] = field(default_factory=dict)
    log_summary: dict[str, object] = field(default_factory=dict)
    session_path: str | None = None
    phases: tuple[dict[str, str], ...] = ()


def headless_run_stats(session: AgentSession) -> dict[str, object]:
    task_counts = _headless_task_counts(getattr(session, "tasks", []) or [])
    return {
        "message_count": session.message_count,
        "context_tokens_estimate": session.context_tokens_estimate,
        "error_count": len(getattr(session, "error_history", [])),
        "compaction_count": session.compaction_count,
        "model_turn_count": getattr(session, "model_turn_count", 0),
        "tool_call_count": getattr(session, "tool_call_count", 0),
        "reflection_count": getattr(session, "reflection_count", 0),
        "pending_verifies": sorted(getattr(session, "pending_verifies", set())),
        "task_counts": task_counts,
    }


def _headless_task_counts(tasks: list[dict]) -> dict[str, int]:
    return {
        "pending": sum(1 for task in tasks if task.get("status") == "pending"),
        "in_progress": sum(1 for task in tasks if task.get("status") == "in_progress"),
        "done": sum(1 for task in tasks if task.get("status") == "done"),
        "blocked": sum(1 for task in tasks if task.get("status") == "blocked"),
    }


def headless_log_summary(session: AgentSession) -> dict[str, object]:
    tool_outcomes = {
        str(name): bool(ok)
        for name, ok in sorted((getattr(session, "_tool_outcomes", {}) or {}).items())
    }
    recent_errors = []
    for error in (getattr(session, "error_history", []) or [])[-5:]:
        error_type = getattr(error, "error_type", "")
        recent_errors.append(
            {
                "type": getattr(error_type, "value", str(error_type)),
                "tool": getattr(error, "tool_name", ""),
                "message": str(getattr(error, "error_message", ""))[:500],
                "attempt_count": int(getattr(error, "attempt_count", 1) or 1),
            }
        )
    failing_tools = sorted(name for name, ok in tool_outcomes.items() if not ok)
    recovery_suggestions = _headless_recovery_suggestions(session)
    pending_verifies = sorted(getattr(session, "pending_verifies", set()))
    stats = {"task_counts": _headless_task_counts(getattr(session, "tasks", []) or [])}
    termination = getattr(session, "last_termination", "unknown")
    return {
        "termination": termination,
        "tool_outcomes": tool_outcomes,
        "successful_tools": sorted(name for name, ok in tool_outcomes.items() if ok),
        "failing_tools": failing_tools,
        "recent_errors": recent_errors,
        "recovery_suggestions": recovery_suggestions,
        "pending_verifies": pending_verifies,
        "handoff_summary": headless_handoff_summary(
            termination=str(termination),
            failing_tools=failing_tools,
            recent_errors=recent_errors,
            recovery_suggestions=recovery_suggestions,
            pending_verifies=pending_verifies,
            stats=stats,
        ),
    }


def with_headless_approval_receipts(
    log_summary: dict[str, object],
    approval_receipts: list[dict[str, object]],
) -> dict[str, object]:
    if not approval_receipts:
        return log_summary
    enriched = dict(log_summary)
    enriched["approval_receipts"] = [dict(receipt) for receipt in approval_receipts]
    return enriched


def headless_handoff_summary(
    *,
    termination: str,
    failing_tools: list[str],
    recent_errors: list[dict[str, object]],
    recovery_suggestions: list[dict[str, object]],
    pending_verifies: list[str],
    stats: dict[str, object],
) -> dict[str, object]:
    """Deterministic takeover summary for scripts/agents after a headless run.

    This intentionally avoids a second model call. It is a compact, stable
    handoff scaffold derived from runtime state, useful when a run fails,
    exhausts steps, or needs another agent to resume.
    """
    next_steps: list[str] = []
    recovery_actions = [
        action
        for action in (str(item.get("action", "")) for item in recovery_suggestions)
        if action
    ]
    primary_recovery = recovery_suggestions[0] if recovery_suggestions else None
    last_error = recent_errors[-1] if recent_errors else None
    recovery_checklist = headless_recovery_checklist(
        recovery_actions[0] if recovery_actions else "",
        failing_tools=failing_tools,
        pending_verifies=pending_verifies,
        last_error=last_error,
    )
    if pending_verifies:
        next_steps.append("Verify pending edited paths before making more changes.")
    if failing_tools:
        next_steps.append(f"Inspect or rerun failing tool(s): {', '.join(failing_tools)}.")
    if recovery_actions:
        next_steps.append(f"Apply recovery action: {recovery_actions[0]}.")
    if termination == "max_steps_exceeded":
        next_steps.append("Resume from the saved session if session_path is present, or rerun with higher --max-steps.")
    elif termination == "final_failed":
        next_steps.append("Do not treat the final answer as done; resolve failing tools or pending verifies first.")
    elif termination in {"runtime_error", "timeout"}:
        next_steps.append("Fix the runtime condition, then rerun the same prompt with --resume-session if available.")
    elif not next_steps:
        next_steps.append("No immediate recovery action detected.")

    task_counts = stats.get("task_counts", {}) if isinstance(stats.get("task_counts", {}), dict) else {}
    return {
        "status": termination,
        "needs_handoff": termination not in {"final_success", "direct_tool_success", "chat", "final"},
        "failing_tools": failing_tools,
        "pending_verifies": pending_verifies,
        "task_counts": task_counts,
        "last_error": last_error,
        "recovery_actions": recovery_actions,
        "primary_recovery": primary_recovery,
        "recovery_checklist": recovery_checklist,
        "next_steps": next_steps,
    }


def headless_recovery_checklist(
    action: str,
    *,
    failing_tools: list[str],
    pending_verifies: list[str],
    last_error: dict[str, object] | None,
) -> list[str]:
    """Deterministic next checks for the primary recovery action.

    The checklist is intentionally command-agnostic and non-destructive. It gives
    scripts or takeover agents a stable bridge from a recovery action to the
    next inspection steps without requiring another model call.
    """
    checklist: list[str] = []
    if pending_verifies:
        checklist.append("Inspect and verify pending edited paths before new edits.")
    if failing_tools:
        checklist.append(f"Review failing tool output for: {', '.join(failing_tools)}.")
    if last_error:
        tool = str(last_error.get("tool", "") or "unknown")
        err_type = str(last_error.get("type", "") or "unknown")
        checklist.append(f"Start from last_error tool={tool} type={err_type}.")

    if action == "verify_assumption":
        checklist.extend([
            "Read the relevant source and test files before editing.",
            "Run the smallest targeted verification that can prove or disprove the assumption.",
        ])
    elif action == "backtrack":
        checklist.extend([
            "Inspect the current diff and identify the last risky change.",
            "Propose the minimal revert or corrective edit; do not run destructive reset commands automatically.",
        ])
    elif action == "change_strategy":
        checklist.extend([
            "Stop repeating the same tool sequence.",
            "Write a one-step alternative plan before the next tool call.",
        ])
    elif action == "simplify_scope":
        checklist.extend([
            "Reduce the task to one failing file, command, or behavior.",
            "Defer unrelated cleanup until the focused failure is resolved.",
        ])
    elif action == "retry_with_fix":
        checklist.extend([
            "Correct the path, argument, or missing input first.",
            "Retry only the corrected minimal tool call.",
        ])
    elif action == "retry":
        checklist.extend([
            "Retry once after confirming the failure is transient.",
            "Escalate or change strategy if the same transient failure repeats.",
        ])
    elif action == "reprioritize":
        checklist.extend([
            "Mark or summarize the blocked task before switching focus.",
            "Choose the next smallest unblocked task.",
        ])
    elif action == "escalate_to_user":
        checklist.extend([
            "Stop new code changes for this failure.",
            "Report goal, observed behavior, logs, attempts, and the specific decision needed.",
        ])
    elif action == "request_clarification":
        checklist.extend([
            "Stop assumptions that would change behavior or scope.",
            "Ask the shortest concrete question needed to proceed.",
        ])
    elif action == "reflect_and_adjust":
        checklist.extend([
            "Write the suspected root cause and the next different action.",
            "Proceed only after the new action differs from the failed loop.",
        ])
    elif action == "abandon_and_restart":
        checklist.extend([
            "Preserve current findings and constraints.",
            "Draft a new approach before touching code again.",
        ])

    if not checklist:
        checklist.append("No deterministic recovery checklist available; inspect recent errors before continuing.")
    return checklist


def _headless_recovery_suggestions(session: AgentSession) -> list[dict[str, object]]:
    details = getattr(session, "last_recovery_suggestion_details", None)
    if details:
        return [
            {
                "action": str(item.get("action", "")),
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "description": str(item.get("description", "")),
                "rationale": str(item.get("rationale", "")),
            }
            for item in details
            if isinstance(item, dict)
        ]

    actions = getattr(session, "last_recovery_suggestions", None)
    if actions:
        return [{"action": str(action)} for action in actions]
    return []


def headless_payload(result: HeadlessRunResult, exit_code: int) -> dict[str, object]:
    log_summary = dict(result.log_summary)
    if isinstance(log_summary.get("handoff_summary"), dict):
        log_summary["handoff_summary"] = headless_handoff_with_resume(
            log_summary["handoff_summary"],  # type: ignore[arg-type]
            result.session_path,
        )
    recommended_command, recommended_kind, recommended_risk = _headless_recommendation(log_summary)
    payload = {
        "schema_version": HEADLESS_PAYLOAD_SCHEMA_VERSION,
        "output": result.output,
        "exit_code": exit_code,
        "termination": result.termination,
        "failing_tools": list(result.failing_tools),
        "recommended_command": recommended_command,
        "recommended_kind": recommended_kind,
        "recommended_risk": recommended_risk,
        "stats": result.stats,
        "log_summary": log_summary,
        "session_path": result.session_path,
    }
    if result.phases:
        payload["phases"] = list(result.phases)
    return payload


def _headless_recommendation(log_summary: dict[str, object]) -> tuple[str | None, str | None, str | None]:
    handoff = log_summary.get("handoff_summary")
    if not isinstance(handoff, dict):
        return None, None, None
    if handoff.get("needs_handoff") is not True:
        return None, None, None
    resume_command = handoff.get("resume_command")
    if resume_command:
        return str(resume_command), "resume_headless", "YELLOW"
    return "inspect log_summary.handoff_summary before continuing", "manual_handoff", "UNKNOWN"


def headless_handoff_with_resume(
    handoff_summary: dict[str, object],
    session_path: str | None,
) -> dict[str, object]:
    enriched = dict(handoff_summary)
    enriched["session_path"] = session_path
    if not session_path:
        enriched["resume_session"] = None
        enriched["resume_command"] = None
        return enriched

    resume_session = Path(session_path).name
    enriched["resume_session"] = resume_session
    enriched["resume_command"] = (
        "agentx -p '<next prompt>' --agent "
        f"--resume-session {shlex.quote(resume_session)} --json"
    )
    next_steps = list(enriched.get("next_steps", []) or [])
    if not any("resume-session" in str(step) for step in next_steps):
        next_steps.append("Resume with the provided resume_command.")
    enriched["next_steps"] = next_steps
    return enriched


def headless_json_payload(result: HeadlessRunResult, exit_code: int) -> str:
    return json.dumps(headless_payload(result, exit_code), ensure_ascii=False)


def headless_payload_text(
    result: HeadlessRunResult,
    exit_code: int,
    *,
    output_format: str = "json",
) -> str:
    return structured_payload_text(
        headless_payload(result, exit_code),
        output_format=output_format,
        event="result",
    )


def print_headless_payload(
    result: HeadlessRunResult,
    exit_code: int,
    *,
    output_format: str = "json",
) -> None:
    print_json_output(headless_payload_text(result, exit_code, output_format=output_format))


def headless_exception_result(exc: Exception, *, session_path: str | None = None) -> HeadlessRunResult:
    message = f"{type(exc).__name__}: {exc}"
    recent_errors: list[dict[str, object]] = [
        {
            "type": "runtime_error",
            "tool": "",
            "message": message[:500],
            "attempt_count": 1,
        }
    ]
    return HeadlessRunResult(
        output=f"runtime error: {message}",
        termination="runtime_error",
        session_path=session_path,
        log_summary={
            "termination": "runtime_error",
            "tool_outcomes": {},
            "successful_tools": [],
            "failing_tools": [],
            "recent_errors": recent_errors,
            "recovery_suggestions": [],
            "handoff_summary": headless_handoff_summary(
                termination="runtime_error",
                failing_tools=[],
                recent_errors=recent_errors,
                recovery_suggestions=[],
                pending_verifies=[],
                stats={"task_counts": {}},
            ),
            "pending_verifies": [],
        },
    )


def headless_timeout_result(seconds: float, *, session_path: str | None = None) -> HeadlessRunResult:
    message = f"run timed out after {seconds:g}s"
    recent_errors: list[dict[str, object]] = [
        {
            "type": "timeout",
            "tool": "",
            "message": message,
            "attempt_count": 1,
        }
    ]
    return HeadlessRunResult(
        output=message,
        termination="timeout",
        session_path=session_path,
        log_summary={
            "termination": "timeout",
            "tool_outcomes": {},
            "successful_tools": [],
            "failing_tools": [],
            "recent_errors": recent_errors,
            "recovery_suggestions": [],
            "handoff_summary": headless_handoff_summary(
                termination="timeout",
                failing_tools=[],
                recent_errors=recent_errors,
                recovery_suggestions=[],
                pending_verifies=[],
                stats={"task_counts": {}},
            ),
            "pending_verifies": [],
        },
    )


def run_with_headless_timeout(
    runner: "Callable[[threading.Event | None], str | HeadlessRunResult]",
    *,
    run_timeout: float | None,
    session_output_path: Path | None = None,
) -> str | HeadlessRunResult:
    if run_timeout is None:
        return runner(None)
    if run_timeout <= 0:
        raise typer.BadParameter("--run-timeout must be greater than 0")

    cancel_event = threading.Event()
    results: queue.Queue[str | HeadlessRunResult | Exception] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            results.put(runner(cancel_event))
        except Exception as exc:
            results.put(exc)

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(run_timeout)
    if worker.is_alive():
        cancel_event.set()
        return headless_timeout_result(
            run_timeout,
            session_path=str(session_output_path) if session_output_path and session_output_path.exists() else None,
        )

    result = results.get()
    if isinstance(result, Exception):
        raise result
    return result


def normalize_output_format(output_format: str | None) -> str:
    normalized = (output_format or "plain").strip().lower()
    if normalized not in {"plain", "json", "jsonl"}:
        raise typer.BadParameter("output format must be one of: plain, json, jsonl")
    return normalized


def structured_output_format(json_output: bool, output_format: str | None) -> str:
    normalized = normalize_output_format(output_format)
    if normalized == "jsonl":
        return "jsonl"
    if json_output or normalized == "json":
        return "json"
    return "plain"


def wants_json_output(json_output: bool, output_format: str | None) -> bool:
    return structured_output_format(json_output, output_format) != "plain"


def wants_jsonl_output(json_output: bool, output_format: str | None) -> bool:
    return structured_output_format(json_output, output_format) == "jsonl"


def structured_payload_text(payload: object, *, output_format: str = "json", event: str = "result") -> str:
    if output_format == "jsonl":
        return json.dumps({"event": event, "data": payload}, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def print_structured_payload(payload: object, *, output_format: str = "json", event: str = "result") -> None:
    print_json_output(structured_payload_text(payload, output_format=output_format, event=event))


def parse_headless_payload_text(text: str) -> dict[str, object]:
    text = text.strip()
    if not text:
        raise typer.BadParameter("payload file is empty")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
        if parsed is None:
            raise typer.BadParameter("payload file must contain JSON or JSONL objects") from None

    if not isinstance(parsed, dict):
        raise typer.BadParameter("payload root must be a JSON object")
    data = parsed.get("data") if parsed.get("event") else parsed
    if not isinstance(data, dict):
        raise typer.BadParameter("payload data must be a JSON object")
    return data


def load_headless_payload_file(path: Path) -> dict[str, object]:
    return parse_headless_payload_text(path.read_text(encoding="utf-8"))


def load_headless_payload_source(source: str) -> dict[str, object]:
    if source == "-":
        return parse_headless_payload_text(sys.stdin.read())
    path = Path(source)
    if not path.is_file():
        raise typer.BadParameter(f"payload file not found: {source}")
    return load_headless_payload_file(path)


def resolve_handoff_resume_payload_source(source: str) -> tuple[Path, Path | None]:
    path = Path(source).expanduser()
    if path.is_dir():
        candidates = [candidate for candidate in (path / "result.json", path / "result.jsonl") if candidate.is_file()]
        if not candidates:
            raise typer.BadParameter(f"artifact dir missing result.json or result.jsonl: {source}")
        if len(candidates) > 1:
            raise typer.BadParameter(f"artifact dir has both result.json and result.jsonl: {source}")
        return candidates[0], path / "handoff.md"
    if path.is_file():
        return path, None
    raise typer.BadParameter(f"handoff resume source not found: {source}")


def load_handoff_resume_payload_source(source: str) -> tuple[dict[str, object], Path | None]:
    payload_path, default_prompt_file = resolve_handoff_resume_payload_source(source)
    return load_headless_payload_file(payload_path), default_prompt_file


def inspect_headless_handoff_payload(payload: dict[str, object]) -> dict[str, object]:
    log_summary = payload.get("log_summary")
    if not isinstance(log_summary, dict):
        raise typer.BadParameter("payload missing log_summary object")
    handoff = log_summary.get("handoff_summary")
    if not isinstance(handoff, dict):
        raise typer.BadParameter("payload missing log_summary.handoff_summary object")

    return {
        "schema_version": payload.get("schema_version"),
        "status": handoff.get("status"),
        "needs_handoff": bool(handoff.get("needs_handoff", False)),
        "termination": payload.get("termination"),
        "exit_code": payload.get("exit_code"),
        "session_path": handoff.get("session_path") or payload.get("session_path"),
        "resume_session": handoff.get("resume_session"),
        "resume_command": handoff.get("resume_command"),
        "failing_tools": list(handoff.get("failing_tools") or []),
        "pending_verifies": list(handoff.get("pending_verifies") or []),
        "recovery_actions": list(handoff.get("recovery_actions") or []),
        "primary_recovery": handoff.get("primary_recovery"),
        "recovery_checklist": list(handoff.get("recovery_checklist") or []),
        "next_steps": list(handoff.get("next_steps") or []),
    }


def apply_handoff_next_prompt(payload: dict[str, object], next_prompt: str | None) -> dict[str, object]:
    if not next_prompt:
        return payload
    enriched = dict(payload)
    command = enriched.get("resume_command")
    if isinstance(command, str) and "<next prompt>" in command:
        quoted_prompt = shlex.quote(next_prompt)
        if "'<next prompt>'" in command:
            enriched["resume_command"] = command.replace("'<next prompt>'", quoted_prompt)
        else:
            enriched["resume_command"] = command.replace("<next prompt>", quoted_prompt)
    return enriched


def apply_handoff_next_prompt_file(payload: dict[str, object], next_prompt_file: str | None) -> dict[str, object]:
    if not next_prompt_file:
        return payload
    enriched = dict(payload)
    command = enriched.get("resume_command")
    if isinstance(command, str):
        quoted_path = shlex.quote(next_prompt_file)
        if " -p '<next prompt>' " in command:
            enriched["resume_command"] = command.replace(" -p '<next prompt>' ", f" --prompt-file {quoted_path} ")
        elif ' -p "<next prompt>" ' in command:
            enriched["resume_command"] = command.replace(' -p "<next prompt>" ', f" --prompt-file {quoted_path} ")
        elif " -p <next prompt> " in command:
            enriched["resume_command"] = command.replace(" -p <next prompt> ", f" --prompt-file {quoted_path} ")
    return enriched


def apply_handoff_resume_output_format(payload: dict[str, object], resume_output_format: str | None) -> dict[str, object]:
    if not resume_output_format:
        return payload
    normalized = resume_output_format.strip().lower()
    if normalized not in {"json", "jsonl"}:
        raise typer.BadParameter("resume output format must be one of: json, jsonl")

    enriched = dict(payload)
    command = enriched.get("resume_command")
    if not isinstance(command, str):
        return enriched

    parts = shlex.split(command)
    rewritten: list[str] = []
    skip_next = False
    for part in parts:
        if skip_next:
            skip_next = False
            continue
        if part == "--json":
            continue
        if part == "--output-format":
            skip_next = True
            continue
        if part.startswith("--output-format="):
            continue
        rewritten.append(part)

    if normalized == "json":
        rewritten.append("--json")
    else:
        rewritten.extend(["--output-format", "jsonl"])
    enriched["resume_command"] = shlex.join(rewritten)
    return enriched


def format_handoff_inspect_plain(payload: dict[str, object]) -> str:
    lines = [
        f"schema_version: {payload.get('schema_version')}",
        f"status: {payload.get('status')}",
        f"needs_handoff: {str(payload.get('needs_handoff')).lower()}",
        f"termination: {payload.get('termination')}",
        f"exit_code: {payload.get('exit_code')}",
        f"session_path: {payload.get('session_path')}",
        f"resume_session: {payload.get('resume_session')}",
        f"resume_command: {payload.get('resume_command')}",
    ]
    for title, key in [
        ("failing_tools", "failing_tools"),
        ("pending_verifies", "pending_verifies"),
        ("recovery_actions", "recovery_actions"),
        ("recovery_checklist", "recovery_checklist"),
        ("next_steps", "next_steps"),
    ]:
        lines.append(f"{title}:")
        values = payload.get(key)
        if isinstance(values, list) and values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- (none)")
    return "\n".join(lines)


def format_handoff_briefing_markdown(payload: dict[str, object]) -> str:
    def scalar(value: object) -> str:
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if value is None:
            return ""
        return str(value)

    def markdown_list(values: object) -> list[str]:
        if isinstance(values, list) and values:
            return [f"- {scalar(value)}" for value in values]
        return ["- (none)"]

    lines = [
        "# agentX Handoff Briefing",
        "",
        f"Schema Version: {scalar(payload.get('schema_version'))}",
        f"Status: {scalar(payload.get('status'))}",
        f"Termination: {scalar(payload.get('termination'))}",
        f"Exit Code: {scalar(payload.get('exit_code'))}",
        f"Needs Handoff: {str(bool(payload.get('needs_handoff'))).lower()}",
        f"Session Path: {scalar(payload.get('session_path'))}",
        f"Resume Session: {scalar(payload.get('resume_session'))}",
        "",
        "## Resume Command",
        "",
        "```bash",
        scalar(payload.get("resume_command")),
        "```",
        "",
        "## Failing Tools",
        *markdown_list(payload.get("failing_tools")),
        "",
        "## Pending Verifies",
        *markdown_list(payload.get("pending_verifies")),
        "",
        "## Recovery Actions",
        *markdown_list(payload.get("recovery_actions")),
        "",
        "## Primary Recovery",
        "",
        scalar(payload.get("primary_recovery")) or "(none)",
        "",
        "## Recovery Checklist",
        *markdown_list(payload.get("recovery_checklist")),
        "",
        "## Next Steps",
        *markdown_list(payload.get("next_steps")),
        "",
    ]
    return "\n".join(lines)


def resolve_handoff_briefing_output(workspace: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    try:
        target = resolve_inside_workspace(workspace, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if target.exists():
        raise typer.BadParameter(f"briefing output already exists: {value}")
    if target.name in {"", ".", ".."}:
        raise typer.BadParameter(f"invalid briefing output path: {value}")
    return target


def write_handoff_briefing_output(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_handoff_briefing_markdown(payload), encoding="utf-8")


def handoff_inspect_field_payload(payload: dict[str, object], field: str) -> dict[str, object]:
    normalized = field.strip()
    if normalized not in payload:
        allowed = ", ".join(sorted(payload))
        raise typer.BadParameter(f"unknown handoff inspect field: {field}. Use one of: {allowed}")
    return {"field": normalized, "value": payload[normalized]}


def format_handoff_inspect_field_plain(field_payload: dict[str, object]) -> str:
    value = field_payload.get("value")
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def handoff_resume_command_payload(payload: dict[str, object]) -> dict[str, object]:
    command = payload.get("resume_command")
    if command is None:
        command_text = ""
        argv: list[str] = []
    else:
        command_text = str(command)
        try:
            argv = shlex.split(command_text)
        except ValueError as exc:
            raise typer.BadParameter(f"resume command is not shell-parseable: {exc}") from exc
    return {
        "field": "resume_command",
        "value": command_text,
        "argv": argv,
    }


def handoff_inspect_exit_code(payload: dict[str, object], *, use_payload_exit_code: bool) -> int:
    if not use_payload_exit_code:
        return 0
    raw = payload.get("exit_code")
    if isinstance(raw, bool):
        return 1 if raw else 0
    if isinstance(raw, int):
        return max(0, min(raw, 255))
    return 1


def handoff_takeover_ready(payload: dict[str, object]) -> bool:
    return bool(payload.get("needs_handoff")) and bool(payload.get("resume_command"))


def handoff_schema_version_matches(payload: dict[str, object]) -> bool:
    return payload.get("schema_version") == HEADLESS_PAYLOAD_SCHEMA_VERSION


def backend_list_payload() -> list[str]:
    register_builtin_backends()
    return list_registered_backends()


def print_backend_list(*, json_output: bool = False, jsonl_output: bool = False) -> None:
    backends = backend_list_payload()
    if json_output:
        print_structured_payload(
            {"backends": backends},
            output_format="jsonl" if jsonl_output else "json",
            event="backends",
        )
        return
    print_raw("\n".join(backends))


def version_payload() -> dict[str, str]:
    try:
        agentx_version = package_version("agentx")
    except PackageNotFoundError:
        from agentx import __version__

        agentx_version = __version__
    return {
        "agentx": agentx_version,
        "python": sys.version.split()[0],
    }


def print_version(*, json_output: bool = False, jsonl_output: bool = False) -> None:
    payload = version_payload()
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="version",
        )
        return
    print_raw(f"agentx {payload['agentx']}\npython {payload['python']}")


def print_command_catalog(
    query: str | None = None,
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    payload = command_catalog_payload() if query is None else filtered_command_catalog_payload(query)
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="commands",
        )
        return

    title = "agentX command catalog"
    if payload["query"]:
        title = f"{title}: {payload['query']}"
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Usage")
    table.add_column("Risk")
    table.add_column("Description")
    for item in payload["commands"]:
        command = dict(item)
        risk = str(command["risk"]).split(" - ", 1)[0]
        table.add_row(
            str(command["command"]),
            str(command["usage"]),
            risk,
            str(command["description"]),
        )
    console.print(table)


def print_capabilities(
    query: str | None = None,
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    payload = capabilities_payload(query)
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="capabilities",
        )
        return

    title = "agentX capabilities"
    if payload["query"]:
        title = f"{title}: {payload['query']}"
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Schema/Event")
    table.add_column("Description")
    for item in payload["capabilities"]:  # type: ignore[index]
        capability = dict(item)
        schemas = ", ".join(str(schema) for schema in capability["schemas"]) or "-"
        table.add_row(
            str(capability["command"]),
            f"{schemas} / {capability['jsonl_event']}",
            str(capability["description"]),
        )
    console.print(table)


def build_headless_dry_run_payload(
    prompt: str,
    *,
    workspace_override: Path | None = None,
    namespace: str | None = None,
    agent_mode: bool = False,
    plan_mode: bool = False,
    plan_then_execute: bool = False,
    orchestrate: bool = False,
    approval_override: str | None = None,
    backend_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    timeout_override: float | None = None,
    run_timeout: float | None = None,
    max_steps: int | None = None,
    save_session: bool = False,
    resume_session: str | None = None,
    session_output: Path | None = None,
    result_output: Path | None = None,
    result_output_format: str = "auto",
    handoff_briefing_output: Path | None = None,
    artifact_dir: Path | None = None,
    no_memory: bool = False,
) -> dict[str, object]:
    settings = Settings(workspace=workspace_override)
    if base_url_override:
        settings = settings.with_updates(ollama_url=base_url_override)
    if model_override:
        settings = settings.with_updates(model=model_override)
    if timeout_override is not None:
        settings = settings.with_updates(ollama_timeout=timeout_override)
    if max_steps is not None:
        settings = settings.with_updates(max_steps=max_steps)
    if session_output is not None and resume_session:
        raise typer.BadParameter("--session-output cannot be combined with --resume-session")

    project_config = load_project_config(settings.workspace)
    approval_value = approval_override or project_config.approval
    approval_mode: str | None = None
    if approval_value:
        try:
            approval_mode = normalize_approval_mode(approval_value).value
        except ValueError as exc:
            raise typer.BadParameter(
                "approval must be one of: ask, auto, off, strict, auto-approve, deny"
            ) from exc

    return {
        "dry_run": True,
        "workspace": str(settings.workspace),
        "namespace": namespace or project_config.namespace or "project:agentX",
        "agent_mode": agent_mode,
        "plan_mode": plan_mode,
        "plan_then_execute": plan_then_execute,
        "orchestrate": orchestrate,
        "backend": (backend_override or os.getenv("AGENTX_BACKEND", "ollama")).lower(),
        "base_url": settings.ollama_url,
        "model": settings.model,
        "timeout": settings.ollama_timeout,
        "run_timeout": run_timeout,
        "max_steps": settings.max_steps,
        "no_memory": no_memory,
        "approval": approval_mode,
        "save_session": save_session or session_output is not None,
        "resume_session": resume_session,
        "session_output": str(session_output) if session_output else None,
        "result_output": str(result_output) if result_output else None,
        "result_output_format": result_output_format,
        "handoff_briefing_output": str(handoff_briefing_output) if handoff_briefing_output else None,
        "artifact_dir": str(artifact_dir) if artifact_dir else None,
        "prompt_chars": len(prompt),
    }


def format_headless_dry_run(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "headless dry run",
            f"workspace: {payload['workspace']}",
            f"namespace: {payload['namespace']}",
            f"backend: {payload['backend']}",
            f"base_url: {payload['base_url']}",
            f"model: {payload['model']}",
            f"timeout: {payload['timeout']}",
            f"run_timeout: {payload['run_timeout']}",
            f"max_steps: {payload['max_steps']}",
            f"no_memory: {payload['no_memory']}",
            f"approval: {payload['approval']}",
            f"agent_mode: {payload['agent_mode']}",
            f"plan_mode: {payload['plan_mode']}",
            f"plan_then_execute: {payload['plan_then_execute']}",
            f"orchestrate: {payload['orchestrate']}",
            f"save_session: {payload['save_session']}",
            f"resume_session: {payload['resume_session']}",
            f"session_output: {payload['session_output']}",
            f"result_output: {payload['result_output']}",
            f"result_output_format: {payload['result_output_format']}",
            f"handoff_briefing_output: {payload['handoff_briefing_output']}",
            f"artifact_dir: {payload['artifact_dir']}",
            f"prompt_chars: {payload['prompt_chars']}",
        ]
    )


def print_headless_dry_run(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
    quiet: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="dry_run",
        )
        return
    if not quiet:
        print_raw(format_headless_dry_run(payload))


def model_list_payload(
    *,
    workspace_override: Path | None = None,
    backend_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    timeout_override: float | None = None,
) -> dict[str, object]:
    settings = Settings(workspace=workspace_override)
    if base_url_override:
        settings = settings.with_updates(ollama_url=base_url_override)
    if model_override:
        settings = settings.with_updates(model=model_override)
    if timeout_override is not None:
        settings = settings.with_updates(ollama_timeout=timeout_override)

    register_builtin_backends()
    backend = (backend_override or os.getenv("AGENTX_BACKEND", "ollama")).lower()
    client = get_llm_client(
        backend,
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    try:
        models = client.list_models()
    finally:
        client.close()

    return {
        "backend": backend,
        "base_url": settings.ollama_url,
        "models": models,
    }


def print_model_list(payload: dict[str, object], *, json_output: bool = False, jsonl_output: bool = False) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="models",
        )
        return
    print_raw("\n".join(str(model) for model in payload["models"]))


def resolve_headless_workspace(workspace: str | None) -> Path | None:
    if workspace is None:
        return None
    resolved = Path(workspace).expanduser().resolve()
    if not resolved.is_dir():
        raise typer.BadParameter(f"workspace is not a directory: {workspace}")
    return resolved


def load_headless_prompt(
    print_prompt: str | None,
    prompt_file: str | None,
    workspace: Path,
    *,
    stdin_prompt: bool = False,
    stdin_reader: object | None = None,
) -> str | None:
    sources = sum(1 for enabled in (print_prompt is not None, prompt_file is not None, stdin_prompt) if enabled)
    if sources > 1:
        raise typer.BadParameter("use only one prompt source: -p/--print, --prompt-file, or --stdin")
    if stdin_prompt:
        reader = stdin_reader or sys.stdin
        return reader.read()
    if prompt_file is None:
        return print_prompt

    target = resolve_inside_workspace(workspace, prompt_file)
    if not target.is_file():
        raise typer.BadParameter(f"prompt file not found: {prompt_file}")
    return target.read_text(encoding="utf-8", errors="replace")


def resolve_session_store_path(workspace: Path, value: str) -> Path:
    sessions_dir = (workspace / ".agentx" / "sessions").resolve()
    if value.strip() == "latest":
        candidates = sorted(sessions_dir.glob("*.session.jsonl")) if sessions_dir.exists() else []
        if not candidates:
            raise FileNotFoundError("No saved headless session found.")
        return candidates[-1]

    raw = Path(value)
    candidates: list[Path]
    if raw.is_absolute():
        candidates = [raw]
    else:
        candidates = [
            sessions_dir / raw,
            sessions_dir / f"{raw}.session.jsonl",
            sessions_dir / f"{raw}.jsonl",
        ]

    for candidate in candidates:
        resolved = candidate.resolve()
        if sessions_dir in resolved.parents and resolved.is_file():
            return resolved
    raise FileNotFoundError(f"Saved headless session not found in {sessions_dir}: {value}")


def resolve_headless_session_output(workspace: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    target = resolve_inside_workspace(workspace, value)
    if target.exists():
        raise typer.BadParameter(f"session output already exists: {value}")
    if target.name in {"", ".", ".."}:
        raise typer.BadParameter(f"invalid session output path: {value}")
    return target


def resolve_headless_result_output(workspace: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    target = resolve_inside_workspace(workspace, value)
    if target.exists():
        raise typer.BadParameter(f"result output already exists: {value}")
    if target.name in {"", ".", ".."}:
        raise typer.BadParameter(f"invalid result output path: {value}")
    return target


def resolve_headless_artifact_dir(workspace: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    try:
        target = resolve_inside_workspace(workspace, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if target.exists() and not target.is_dir():
        raise typer.BadParameter(f"artifact dir is not a directory: {value}")
    if target.name in {"", ".", ".."}:
        raise typer.BadParameter(f"invalid artifact dir path: {value}")
    return target


def reject_artifact_dir_output_overrides(
    artifact_dir: Path | None,
    *,
    session_output: str | None,
    result_output: str | None,
    handoff_briefing_output: str | None,
) -> None:
    if artifact_dir is None:
        return
    conflicts = [
        name
        for name, value in [
            ("--session-output", session_output),
            ("--result-output", result_output),
            ("--handoff-briefing-output", handoff_briefing_output),
        ]
        if value is not None
    ]
    if conflicts:
        joined = ", ".join(conflicts)
        raise typer.BadParameter(f"--artifact-dir cannot be combined with {joined}")


def artifact_bundle_paths(
    artifact_dir: Path | None,
    *,
    result_output_format: str,
) -> tuple[Path | None, Path | None, Path | None]:
    if artifact_dir is None:
        return None, None, None
    result_suffix = "jsonl" if result_output_format == "jsonl" else "json"
    return (
        artifact_dir / "session.session.jsonl",
        artifact_dir / f"result.{result_suffix}",
        artifact_dir / "handoff.md",
    )


def ensure_headless_output_paths_available(
    *paths: tuple[str, Path | None],
) -> None:
    for label, path in paths:
        if path is not None and path.exists():
            raise typer.BadParameter(f"{label} already exists: {path}")


def write_headless_result_output(
    path: Path | None,
    result: HeadlessRunResult,
    exit_code: int,
    *,
    output_format: str,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        headless_payload_text(result, exit_code, output_format=output_format) + "\n",
        encoding="utf-8",
    )


def ensure_distinct_headless_output_paths(
    *paths: tuple[str, Path | None],
) -> None:
    seen: dict[Path, str] = {}
    for label, path in paths:
        if path is None:
            continue
        resolved = path.resolve()
        if resolved in seen:
            raise typer.BadParameter(f"{label} must differ from {seen[resolved]}")
        seen[resolved] = label


def write_headless_handoff_briefing_output(
    path: Path | None,
    result: HeadlessRunResult,
    exit_code: int,
) -> None:
    if path is None:
        return
    payload = inspect_headless_handoff_payload(headless_payload(result, exit_code))
    write_handoff_briefing_output(path, payload)


def resolve_headless_result_output_format(value: str | None, *, stdout_format: str) -> str:
    normalized = (value or "auto").strip().lower()
    if normalized == "auto":
        return "jsonl" if stdout_format == "jsonl" else "json"
    if normalized not in {"json", "jsonl"}:
        raise typer.BadParameter("result output format must be one of: auto, json, jsonl")
    return normalized


def structured_headless_exit_code(
    termination: str | None,
    failing_tools: list[str] | set[str] | tuple[str, ...] | None = None,
) -> int | None:
    normalized = (termination or "").strip().lower()
    failing = tuple(failing_tools or ())
    if not normalized or normalized == "unknown":
        return None
    if normalized in {"cancelled", "canceled", "request_cancelled"}:
        return 130
    if normalized in {"timeout", "timed_out", "run_timeout"}:
        return 124
    if normalized in {"max_steps_exceeded", "invalid_action", "bad_schema", "non_json", "runtime_error"}:
        return 2
    if normalized in {"direct_tool_failure", "tool_failure", "final_failed"}:
        return 1
    if normalized in {"final", "final_success", "direct_tool", "direct_tool_success", "chat"}:
        return 1 if failing else 0
    return None


def headless_exit_code(
    output: str,
    *,
    termination: str | None = None,
    failing_tools: list[str] | set[str] | tuple[str, ...] | None = None,
) -> int:
    structured = structured_headless_exit_code(termination, failing_tools)
    if structured is not None:
        return structured
    normalized = " ".join((output or "").strip().split()).lower()
    if not normalized:
        return 2
    if any(marker in normalized for marker in ("cancelled", "request cancelled", "ollama request cancelled")):
        return 130
    if any(
        marker in normalized
        for marker in (
            "模型沒有輸出有效的工具呼叫 json",
            "max_steps_exceeded",
            "invalid response",
            "bad_schema",
            "non_json",
        )
    ):
        return 2
    if any(
        marker in normalized
        for marker in (
            "任務失敗",
            "工具執行失敗",
            "tests failed",
            "tool is blocked",
            "permissionerror",
            "traceback",
        )
    ):
        return 1
    return 0


def run_init(settings: Settings, tools: ToolRegistry, namespace: str) -> str:
    profile = build_project_profile(settings.workspace, namespace)
    # /init is explicit user action → human_confirmed (ACA L2)
    result = tools.run(
        "memory_write",
        {
            "content": profile,
            "namespace": namespace,
            "tier": "human_confirmed",
            "memory_type": "fact",
        },
    )
    if result.ok:
        return "project profile written to Memory Hall (human_confirmed, ACA L2)\n\n" + profile[:4000]
    return "project profile write failed\n\n" + result.content


def init_payload(
    settings: Settings,
    *,
    namespace: str,
    write_memory: bool = False,
    memory_result: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = build_project_profile_payload(settings.workspace, namespace)
    return {
        "schema": "agentx.init.v1",
        "workspace": str(settings.workspace),
        "namespace": namespace,
        "write_memory": write_memory,
        "memory_result": memory_result,
        "profile": payload,
    }


def print_init_payload(
    payload: dict[str, object],
    *,
    json_output: bool = False,
    jsonl_output: bool = False,
) -> None:
    if json_output:
        print_structured_payload(
            payload,
            output_format="jsonl" if jsonl_output else "json",
            event="init",
        )
        return

    profile = dict(payload["profile"])  # type: ignore[arg-type]
    table = Table(title="agentX init", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("workspace", str(payload["workspace"]))
    table.add_row("namespace", str(payload["namespace"]))
    table.add_row("detected", ", ".join(str(item) for item in profile.get("detected", [])) or "unknown")
    table.add_row("test_commands", ", ".join(str(item) for item in profile.get("test_commands", [])) or "unknown")
    table.add_row("write_memory", str(payload["write_memory"]))
    if payload.get("memory_result") is not None:
        table.add_row("memory_result", json.dumps(payload["memory_result"], ensure_ascii=False))
    console.print(table)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    print_prompt: str | None = typer.Option(None, "-p", "--print", help="Print one response and exit."),
    prompt_file: str | None = typer.Option(None, "--prompt-file", help="Read the headless prompt from a workspace file."),
    stdin_prompt: bool = typer.Option(False, "--stdin", help="Read the headless prompt from stdin."),
    agent: bool = typer.Option(False, "--agent", help="Use agent/tool mode with -p."),
    plan: bool = typer.Option(False, "--plan", help="Start in pure planning mode for -p (only produce high-quality plan + reflection, no tools)."),
    plan_then_execute: bool = typer.Option(False, "--plan-then-execute", help="Plan thoroughly first, then seamlessly continue into execution in the same run (recommended for complex tasks)."),
    orchestrate: bool = typer.Option(False, "--orchestrate", help="Multi-agent orchestration: plan → split → parallel workers."),
    namespace: str | None = typer.Option(None, "--namespace", help="Memory Hall namespace for -p."),
    list_backends: bool = typer.Option(False, "--list-backends", help="List registered LLM backend keys and exit."),
    list_models: bool = typer.Option(False, "--list-models", help="List models for the selected LLM backend and exit."),
    show_version: bool = typer.Option(False, "--version", help="Show agentX and Python versions and exit."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Run this headless task against a specific workspace directory."),
    approval: str | None = typer.Option(None, "--approval", help="Override approval policy for this headless run: ask, auto, off, strict, auto-approve, or deny."),
    backend: str | None = typer.Option(None, "--backend", help="Override LLM backend for this headless run."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override LLM backend base URL for this headless run."),
    model: str | None = typer.Option(None, "--model", help="Override model for this headless run."),
    timeout: float | None = typer.Option(None, "--timeout", help="Override LLM request timeout seconds for this headless run."),
    run_timeout: float | None = typer.Option(None, "--run-timeout", help="Limit total headless run time in seconds; returns exit 124 on timeout."),
    max_steps: int | None = typer.Option(None, "--max-steps", help="Override max agent loop steps for -p."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result for headless automation."),
    output_format: str = typer.Option("plain", "--output-format", help="Headless output format: plain, json, or jsonl."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress plain stdout for headless automation; JSON output is still printed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate headless options and print the normalized run configuration without calling the model."),
    save_session: bool = typer.Option(False, "--save-session", help="Persist the headless agent session for later resume."),
    resume_session: str | None = typer.Option(None, "--resume-session", help="Resume a saved headless session: latest, NAME, or NAME.session.jsonl."),
    session_output: str | None = typer.Option(None, "--session-output", help="Write the headless session JSONL artifact to a specific workspace path."),
    result_output: str | None = typer.Option(None, "--result-output", help="Write the headless result JSON/JSONL payload to a specific workspace path."),
    result_output_format: str = typer.Option("auto", "--result-output-format", help="Result artifact format: auto, json, or jsonl."),
    handoff_briefing_output: str | None = typer.Option(None, "--handoff-briefing-output", help="Write a Markdown handoff briefing artifact to a specific workspace path."),
    artifact_dir: str | None = typer.Option(None, "--artifact-dir", help="Write standard headless artifacts under this workspace directory."),
    no_memory: bool = typer.Option(False, "--no-memory", help="Disable Memory Hall/AMH reads and writes for this headless run."),
) -> None:
    """Run local Ollama agent workflows."""
    if ctx.invoked_subcommand is not None:
        return
    structured_format = structured_output_format(json_output, output_format)
    structured_output = structured_format != "plain"
    jsonl_output = structured_format == "jsonl"
    if list_backends:
        print_backend_list(json_output=structured_output, jsonl_output=jsonl_output)
        raise typer.Exit(code=0)
    if show_version:
        print_version(json_output=structured_output, jsonl_output=jsonl_output)
        raise typer.Exit(code=0)
    workspace_override = resolve_headless_workspace(workspace)
    settings_for_prompt = Settings(workspace=workspace_override)
    artifact_dir_path = resolve_headless_artifact_dir(settings_for_prompt.workspace, artifact_dir)
    reject_artifact_dir_output_overrides(
        artifact_dir_path,
        session_output=session_output,
        result_output=result_output,
        handoff_briefing_output=handoff_briefing_output,
    )
    result_artifact_format = resolve_headless_result_output_format(result_output_format, stdout_format=structured_format)
    bundle_session_output_path, bundle_result_output_path, bundle_handoff_briefing_output_path = artifact_bundle_paths(
        artifact_dir_path,
        result_output_format=result_artifact_format,
    )
    session_output_path = bundle_session_output_path or resolve_headless_session_output(settings_for_prompt.workspace, session_output)
    result_output_path = bundle_result_output_path or resolve_headless_result_output(settings_for_prompt.workspace, result_output)
    handoff_briefing_output_path = bundle_handoff_briefing_output_path or resolve_handoff_briefing_output(settings_for_prompt.workspace, handoff_briefing_output)
    ensure_distinct_headless_output_paths(
        ("--session-output", session_output_path),
        ("--result-output", result_output_path),
        ("--handoff-briefing-output", handoff_briefing_output_path),
    )
    ensure_headless_output_paths_available(
        ("--session-output", session_output_path),
        ("--result-output", result_output_path),
        ("--handoff-briefing-output", handoff_briefing_output_path),
    )
    if artifact_dir_path is not None and not agent:
        raise typer.BadParameter("--artifact-dir requires --agent")
    if handoff_briefing_output_path is not None and not agent:
        raise typer.BadParameter("--handoff-briefing-output requires --agent")
    if list_models:
        payload = model_list_payload(
            workspace_override=workspace_override,
            backend_override=backend,
            base_url_override=base_url,
            model_override=model,
            timeout_override=timeout,
        )
        print_model_list(payload, json_output=structured_output, jsonl_output=jsonl_output)
        raise typer.Exit(code=0)
    prompt = load_headless_prompt(
        print_prompt,
        prompt_file,
        settings_for_prompt.workspace,
        stdin_prompt=stdin_prompt,
    )
    if prompt is None:
        return
    if dry_run:
        payload = build_headless_dry_run_payload(
            prompt,
            workspace_override=workspace_override,
            namespace=namespace,
            agent_mode=agent,
            plan_mode=plan,
            plan_then_execute=plan_then_execute,
            orchestrate=orchestrate,
            approval_override=approval,
            backend_override=backend,
            base_url_override=base_url,
            model_override=model,
            timeout_override=timeout,
            run_timeout=run_timeout,
            max_steps=max_steps,
            save_session=save_session,
            resume_session=resume_session,
            session_output=session_output_path,
            result_output=result_output_path,
            result_output_format=result_artifact_format,
            handoff_briefing_output=handoff_briefing_output_path,
            artifact_dir=artifact_dir_path,
            no_memory=no_memory,
        )
        print_headless_dry_run(payload, json_output=structured_output, jsonl_output=jsonl_output, quiet=quiet)
        raise typer.Exit(code=0)
    try:
        output = run_with_headless_timeout(
            lambda cancel_event: run_print_prompt(
                prompt,
                namespace=namespace,
                agent_mode=agent,
                plan_mode=plan,
                plan_then_execute=plan_then_execute,
                orchestrate=orchestrate,
                workspace_override=workspace_override,
                approval_override=approval,
                backend_override=backend,
                base_url_override=base_url,
                model_override=model,
                timeout_override=timeout,
                cancel_event=cancel_event,
                return_metadata=True,
                suppress_trace=structured_output,
                save_session=save_session,
                resume_session=resume_session,
                session_output_path=session_output_path,
                max_steps=max_steps,
                no_memory=no_memory,
            ),
            run_timeout=run_timeout,
            session_output_path=session_output_path,
        )
    except Exception as exc:
        output = headless_exception_result(exc)
    if isinstance(output, HeadlessRunResult):
        exit_code = headless_exit_code(
            output.output,
            termination=output.termination,
            failing_tools=output.failing_tools,
        )
        write_headless_handoff_briefing_output(handoff_briefing_output_path, output, exit_code)
        if structured_output:
            write_headless_result_output(result_output_path, output, exit_code, output_format=result_artifact_format)
            print_headless_payload(output, exit_code, output_format=structured_format)
            raise typer.Exit(code=exit_code)
        write_headless_result_output(result_output_path, output, exit_code, output_format=result_artifact_format)
        if not quiet:
            print_raw(output.output)
        raise typer.Exit(
            code=exit_code
        )
    if structured_output:
        fallback_result = HeadlessRunResult(output=output)
        fallback_exit_code = headless_exit_code(output)
        write_headless_handoff_briefing_output(handoff_briefing_output_path, fallback_result, fallback_exit_code)
        write_headless_result_output(result_output_path, fallback_result, fallback_exit_code, output_format=result_artifact_format)
        print_headless_payload(
            fallback_result,
            fallback_exit_code,
            output_format=structured_format,
        )
        raise typer.Exit(code=fallback_exit_code)
    fallback_exit_code = headless_exit_code(output)
    fallback_result = HeadlessRunResult(output=output)
    write_headless_handoff_briefing_output(handoff_briefing_output_path, fallback_result, fallback_exit_code)
    write_headless_result_output(result_output_path, fallback_result, fallback_exit_code, output_format=result_artifact_format)
    if not quiet:
        print_raw(output)
    raise typer.Exit(code=fallback_exit_code)


def build_runtime(
    settings: Settings,
    *,
    approval_policy: ApprovalPolicy | None = None,
    approval_audit: Callable[[dict[str, object]], None] | None = None,
    backend_override: str | None = None,
    no_memory: bool = False,
) -> tuple[LLMClient, MemoryHallClient | NullMemoryClient, ToolRegistry]:
    """建立執行時需要的核心物件（LLM client、Memory Hall、Tool Registry）。

    注意（MT22）：此函式已完全與舊的單一任務系統（TaskState）解耦，
    不再回傳或依賴舊的 task 物件。所有任務相關狀態請改用新多任務清單。

    Backend selection now goes through the Provider Registry (borrowed from pi).
    See src/agentx/provider_registry.py and the self-registration in ollama.py / llama_cpp.py.
    """
    import os
    # Ensure built-in backends are registered (idempotent). This must happen
    # at runtime inside the function so it occurs after the whole cli module
    # has finished its top-level imports (avoids E402).
    register_builtin_backends()
    backend = (backend_override or os.getenv("AGENTX_BACKEND", "ollama")).lower()
    llm_client = get_llm_client(
        backend,
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    if no_memory:
        memory = NullMemoryClient()
    elif (settings.memory_backend or "memhall").lower() == "amh":
        from agentx.memory_hall import AmhClient
        # Prefer config.toml values (memory_amh_store / memory_amh_path), env as fallback
        memory = AmhClient(
            store=settings.memory_amh_store,
            store_path=settings.memory_amh_path,
        )
    else:
        memory = MemoryHallClient(
            base_url=settings.memory_hall_url,
            token=settings.memory_hall_token,
        )
    def approve(tool: str, args: dict[str, object], risk: Risk) -> bool:
        if approval_policy is None:
            return False
        allowed = approval_policy.decide(tool, args, risk, approve_interactive)
        if approval_audit is not None:
            approval_audit(
                {
                    "tool": tool,
                    "risk": risk.value,
                    "approval_mode": approval_policy.mode.value,
                    "source": approval_decision_source(approval_policy.mode, allowed),
                    "allowed": allowed,
                }
            )
        return allowed

    tools = ToolRegistry(
        builtin_tools(settings.workspace, memory),
        approver=approve if approval_policy is not None else None,
    )
    return llm_client, memory, tools


def run_print_prompt(
    prompt: str,
    namespace: str | None,
    agent_mode: bool = False,
    plan_mode: bool = False,
    plan_then_execute: bool = False,
    orchestrate: bool = False,
    workspace_override: Path | None = None,
    approval_override: str | None = None,
    backend_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
    timeout_override: float | None = None,
    cancel_event: threading.Event | None = None,
    return_metadata: bool = False,
    suppress_trace: bool = False,
    save_session: bool = False,
    resume_session: str | None = None,
    session_output_path: Path | None = None,
    max_steps: int | None = None,
    no_memory: bool = False,
) -> str | HeadlessRunResult:
    settings = Settings(workspace=workspace_override)
    if base_url_override:
        settings = settings.with_updates(ollama_url=base_url_override)
    if model_override:
        settings = settings.with_updates(model=model_override)
    if timeout_override is not None:
        settings = settings.with_updates(ollama_timeout=timeout_override)
    if max_steps is not None:
        settings = settings.with_updates(max_steps=max_steps)
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"

    # Phase A (MT22): 自動從舊單一任務遷移到多任務清單
    migrate_single_task_if_needed(settings.workspace)

    approval_value = approval_override or project_config.approval
    approval_policy = None
    if approval_value:
        try:
            mode = normalize_approval_mode(approval_value)
        except ValueError:
            output = "invalid response: approval must be one of: ask, auto, off, strict, auto-approve, deny"
            if return_metadata:
                return HeadlessRunResult(output=output, termination="invalid_action")
            return output
        approval_policy = ApprovalPolicy(mode)
    approval_receipts: list[dict[str, object]] = []
    ollama, memory, tools = build_runtime(
        settings,
        approval_policy=approval_policy,
        approval_audit=approval_receipts.append,
        backend_override=backend_override,
        no_memory=no_memory,
    )
    attachment_context, _ = build_attachment_context(prompt, settings.workspace)
    if attachment_context:
        prompt = f"{prompt}\n\n{attachment_context}"

    if resume_session and not agent_mode:
        output = "invalid response: --resume-session requires --agent"
        if return_metadata:
            return HeadlessRunResult(output=output, termination="invalid_action")
        return output
    if session_output_path and not agent_mode:
        output = "invalid response: --session-output requires --agent"
        if return_metadata:
            return HeadlessRunResult(output=output, termination="invalid_action")
        return output
    if session_output_path and resume_session:
        output = "invalid response: --session-output cannot be combined with --resume-session"
        if return_metadata:
            return HeadlessRunResult(output=output, termination="invalid_action")
        return output

    if orchestrate:
        from agentx.orchestrator import Orchestrator
        orch = Orchestrator(
            settings=settings,
            llm=ollama,
            memory=memory,
            tools=tools,
            trace=None if suppress_trace else print_trace,
        )
        result = orch.run(prompt, namespace=namespace)
        if return_metadata:
            return HeadlessRunResult(output=result.summary, termination="final")
        return result.summary
    if agent_mode:
        # Use headless-optimized prompt when running via -p --agent
        # B1: 自動注入當前任務清單摘要，讓模型更容易維持長期任務狀態
        current_tasks = load_tasks(settings.workspace)
        task_summary = format_task_list_summary(current_tasks)
        system_prompt = build_headless_agent_system_prompt(settings.persona, task_summary, model=settings.model)

        agent_prompt = prompt
        plan_prompt = (
            "你目前處於純 PLAN MODE（Headless）。\n"
            "這次你只需要產生高品質規劃，**不要使用任何工具**。\n\n"
            "請先進行完整規劃與認真 Reflection，然後在 final answer 中輸出結構化方案。\n"
            "規劃完成後不要繼續執行。\n\n"
            "使用者任務："
        ) + prompt
        if plan_mode:
            agent_prompt = plan_prompt

        compactor = LLMContextCompactor(ollama) if "gemma" in settings.model.lower() else None
        if resume_session:
            try:
                session_path = resolve_session_store_path(settings.workspace, resume_session)
            except FileNotFoundError as exc:
                output = f"invalid response: {exc}"
                if return_metadata:
                    return HeadlessRunResult(output=output, termination="invalid_action")
                return output
            agent_session = AgentSession.from_session_store(
                session_path,
                settings=settings,
                ollama=ollama,
                tools=tools,
                namespace=namespace,
                compactor=compactor,
                memory=memory,
                trace=None if suppress_trace else print_trace,
            )
            agent_loop = AgentLoop.__new__(AgentLoop)
            agent_loop.session = agent_session
        else:
            agent_loop = AgentLoop(
                settings=settings,
                ollama=ollama,
                tools=tools,
                namespace=namespace,
                system_prompt=system_prompt,
                compactor=compactor,
                trace=None if suppress_trace else print_trace,
                memory=memory,
            )
            session_path = None
        if (save_session or session_output_path is not None) and not getattr(agent_loop.session, "_session_store", None):
            agent_loop.session.enable_persistence(settings.workspace, path=session_output_path)
            session_path = agent_loop.session._session_store.path if agent_loop.session._session_store else session_path
        try:
            if plan_then_execute:
                plan_output = agent_loop.run(plan_prompt, namespace=namespace, plan_only=True, cancel_event=cancel_event)
                execute_prompt = (
                    "你已經完成上一步 headless planning。現在切換到 EXECUTE MODE。\n"
                    "請依照已產出的方案執行使用者任務；必要時使用工具，小步實作並驗證。\n"
                    "不要重新輸出完整計畫，直接從下一個可驗證行動開始。\n\n"
                    f"上一階段計畫：\n{plan_output}\n\n"
                    f"使用者原始任務：{prompt}"
                )
                execute_output = agent_loop.run(execute_prompt, namespace=namespace, plan_only=False, cancel_event=cancel_event)
                output = f"## Plan\n{plan_output}\n\n## Execution\n{execute_output}"
                phases = (
                    {"name": "plan", "output": plan_output},
                    {"name": "execution", "output": execute_output},
                )
            else:
                output = agent_loop.run(agent_prompt, namespace=namespace, plan_only=plan_mode, cancel_event=cancel_event)
                phases = ()
        except Exception as exc:
            active_store = getattr(agent_loop.session, "_session_store", None)
            if active_store is not None:
                session_path = active_store.path
            if return_metadata:
                result = headless_exception_result(
                    exc,
                    session_path=str(session_path) if session_path else None,
                )
                return replace(
                    result,
                    log_summary=with_headless_approval_receipts(
                        result.log_summary,
                        approval_receipts,
                    ),
                )
            return f"runtime error: {type(exc).__name__}: {exc}"
        active_store = getattr(agent_loop.session, "_session_store", None)
        if active_store is not None:
            session_path = active_store.path
        if return_metadata:
            return HeadlessRunResult(
                output=output,
                termination=agent_loop.session.last_termination,
                failing_tools=tuple(sorted(agent_loop.session.last_failing_tools)),
                stats=headless_run_stats(agent_loop.session),
                log_summary=with_headless_approval_receipts(
                    headless_log_summary(agent_loop.session),
                    approval_receipts,
                ),
                session_path=str(session_path) if session_path else None,
                phases=phases,
            )
        return output
    output = ollama.chat(
        [
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona, model=settings.model)},
            {"role": "user", "content": prompt},
        ],
        json_mode=False,
    )
    if return_metadata:
        return HeadlessRunResult(output=output, termination="chat")
    return output


def build_handoff(
    *,
    settings: Settings,
    namespace: str,
    mode: str,
    history: list[tuple[str, str]],
    transcript: Transcript,
    tasks: list[dict] | None = None,
    note: str | None = None,
    task_summary: str | None = None,
) -> str:
    recent = "\n".join(f"- [{item_mode}] {prompt}" for item_mode, prompt in history[-10:])
    note_section = f"\n人類補充：{note}\n" if note else ""
    next_steps = _handoff_next_steps(tasks, task_summary)
    completed = _handoff_completed(tasks)
    todo = _handoff_todo(tasks, task_summary)
    blockers = _handoff_blockers(tasks)

    # MT22 後：只使用新多任務清單（legacy 分支已移除）
    if tasks:
        task_section = f"多任務清單：\n{format_task_list_summary(tasks, max_active=8)}\n"
    elif task_summary:
        task_section = f"多任務清單摘要：\n{task_summary}\n"
    else:
        task_section = "tasks：(none)\n"

    return (
        f"agentX session handoff\n"
        f"時間：{datetime.now().isoformat(timespec='seconds')}\n"
        f"workspace：{settings.workspace}\n"
        f"model：{settings.model}\n"
        f"mode：{mode}\n"
        f"namespace：{namespace}\n"
        f"{task_section}"
        f"transcript：{transcript.path}\n"
        f"{note_section}"
        f"完成：\n{completed}\n"
        f"待辦：\n{todo}\n"
        f"阻塞：\n{blockers}\n"
        f"最近互動：\n{recent if recent else '- 無使用者任務'}\n"
        f"下一輪建議：\n{next_steps}"
    )


def _handoff_completed(tasks: list[dict] | None = None) -> str:
    if not tasks:
        return "- 未記錄完成項目"
    done = [task for task in tasks if task.get("status") == "done"]
    if not done:
        return "- 未記錄完成項目"
    return "\n".join(
        f"- #{task.get('id')}: {task.get('description')} [done]"
        for task in done[:8]
    )


def _handoff_todo(tasks: list[dict] | None = None, task_summary: str | None = None) -> str:
    if tasks:
        active = [
            task for task in tasks
            if task.get("status") not in {"done", "blocked"}
        ]
        if active:
            return "\n".join(
                f"- #{task.get('id')}: {task.get('description')} [{task.get('status', 'pending')}]"
                for task in active[:8]
            )
        return "- 無 active todo"
    if task_summary and task_summary.strip() and "(none)" not in task_summary:
        return "- 見上方多任務清單摘要"
    return "- 無 active todo"


def _handoff_blockers(tasks: list[dict] | None = None) -> str:
    if not tasks:
        return "- 無明確阻塞"
    blocked = [task for task in tasks if task.get("status") == "blocked"]
    if not blocked:
        return "- 無明確阻塞"
    return "\n".join(
        f"- #{task.get('id')}: {task.get('description')} [blocked]"
        for task in blocked[:5]
    )


def _handoff_next_steps(tasks: list[dict] | None = None, task_summary: str | None = None) -> str:
    if tasks:
        active = [task for task in tasks if task.get("status") != "done"]
        if active:
            return "\n".join(
                f"- #{task.get('id')}: {task.get('description')} [{task.get('status', 'pending')}]"
                for task in active[:5]
            )
        return "- 所有目前任務已完成；下一輪先用 /task add 建立新工作。"
    if task_summary and task_summary.strip() and "(none)" not in task_summary:
        return "- 先用 /task status 確認任務清單，再接續未完成項目。"
    return "- 下一輪先用 /resume latest 載入摘要，再用 /guide 或 /task add 開始。"


def write_handoff(
    tools: ToolRegistry,
    *,
    settings: Settings,
    namespace: str,
    mode: str,
    history: list[tuple[str, str]],
    transcript: Transcript,
    tasks: list[dict] | None = None,
    note: str | None = None,
    task_summary: str | None = None,
) -> str:
    content = build_handoff(
        settings=settings,
        namespace=namespace,
        mode=mode,
        history=history,
        transcript=transcript,
        tasks=tasks,
        note=note,
        task_summary=task_summary,
    )
    # Handoff content is largely system-generated from agent run (llm_derived).
    # Human note (if any) is appended but tier remains llm_derived for the record as a whole.
    # Future: support tier_upgrade to human_confirmed on explicit human handoff.
    result = tools.run(
        "memory_write",
        {
            "content": content,
            "namespace": namespace,
            "tier": "llm_derived",
            "memory_type": "handoff",
        },
    )
    if result.ok:
        return f"handoff written to {namespace} (llm_derived, ACA)"
    return f"handoff failed: {result.content}"


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Task or question for agentX."),
    namespace: str | None = typer.Option(None, help="Default Memory Hall namespace."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Run this headless task against a specific workspace directory."),
    approval: str | None = typer.Option(None, "--approval", help="Override approval policy for this headless run: ask, auto, off, strict, auto-approve, or deny."),
    backend: str | None = typer.Option(None, "--backend", help="Override LLM backend for this headless run."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override LLM backend base URL for this headless run."),
    model: str | None = typer.Option(None, "--model", help="Override model for this headless run."),
    timeout: float | None = typer.Option(None, "--timeout", help="Override LLM request timeout seconds."),
    run_timeout: float | None = typer.Option(None, "--run-timeout", help="Limit total headless run time in seconds; returns exit 124 on timeout."),
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
    plan_then_execute: bool = typer.Option(False, "--plan-then-execute", help="Plan first, then execute in the same headless run."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result for automation."),
    output_format: str = typer.Option("plain", "--output-format", help="Headless output format: plain, json, or jsonl."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress plain stdout for automation; JSON output is still printed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate options and print the normalized run configuration without calling the model."),
    save_session: bool = typer.Option(False, "--save-session", help="Persist the headless agent session for later resume."),
    resume_session: str | None = typer.Option(None, "--resume-session", help="Resume a saved headless session: latest, NAME, or NAME.session.jsonl."),
    session_output: str | None = typer.Option(None, "--session-output", help="Write the headless session JSONL artifact to a specific workspace path."),
    result_output: str | None = typer.Option(None, "--result-output", help="Write the headless result JSON/JSONL payload to a specific workspace path."),
    result_output_format: str = typer.Option("auto", "--result-output-format", help="Result artifact format: auto, json, or jsonl."),
    handoff_briefing_output: str | None = typer.Option(None, "--handoff-briefing-output", help="Write a Markdown handoff briefing artifact to a specific workspace path."),
    artifact_dir: str | None = typer.Option(None, "--artifact-dir", help="Write standard headless artifacts under this workspace directory."),
    no_memory: bool = typer.Option(False, "--no-memory", help="Disable Memory Hall/AMH reads and writes for this headless run."),
) -> None:
    structured_format = structured_output_format(json_output, output_format)
    structured_output = structured_format != "plain"
    jsonl_output = structured_format == "jsonl"
    workspace_override = resolve_headless_workspace(workspace)
    settings_for_prompt = Settings(workspace=workspace_override)
    artifact_dir_path = resolve_headless_artifact_dir(settings_for_prompt.workspace, artifact_dir)
    reject_artifact_dir_output_overrides(
        artifact_dir_path,
        session_output=session_output,
        result_output=result_output,
        handoff_briefing_output=handoff_briefing_output,
    )
    result_artifact_format = resolve_headless_result_output_format(result_output_format, stdout_format=structured_format)
    bundle_session_output_path, bundle_result_output_path, bundle_handoff_briefing_output_path = artifact_bundle_paths(
        artifact_dir_path,
        result_output_format=result_artifact_format,
    )
    session_output_path = bundle_session_output_path or resolve_headless_session_output(settings_for_prompt.workspace, session_output)
    result_output_path = bundle_result_output_path or resolve_headless_result_output(settings_for_prompt.workspace, result_output)
    handoff_briefing_output_path = bundle_handoff_briefing_output_path or resolve_handoff_briefing_output(settings_for_prompt.workspace, handoff_briefing_output)
    ensure_distinct_headless_output_paths(
        ("--session-output", session_output_path),
        ("--result-output", result_output_path),
        ("--handoff-briefing-output", handoff_briefing_output_path),
    )
    ensure_headless_output_paths_available(
        ("--session-output", session_output_path),
        ("--result-output", result_output_path),
        ("--handoff-briefing-output", handoff_briefing_output_path),
    )
    if dry_run:
        payload = build_headless_dry_run_payload(
            prompt,
            workspace_override=workspace_override,
            namespace=namespace,
            agent_mode=True,
            plan_then_execute=plan_then_execute,
            approval_override=approval,
            backend_override=backend,
            base_url_override=base_url,
            model_override=model,
            timeout_override=timeout,
            run_timeout=run_timeout,
            max_steps=max_steps,
            save_session=save_session,
            resume_session=resume_session,
            session_output=session_output_path,
            result_output=result_output_path,
            result_output_format=result_artifact_format,
            handoff_briefing_output=handoff_briefing_output_path,
            artifact_dir=artifact_dir_path,
            no_memory=no_memory,
        )
        print_headless_dry_run(payload, json_output=structured_output, jsonl_output=jsonl_output, quiet=quiet)
        raise typer.Exit(code=0)
    try:
        output = run_with_headless_timeout(
            lambda cancel_event: run_print_prompt(
                prompt,
                namespace=namespace,
                agent_mode=True,
                plan_then_execute=plan_then_execute,
                workspace_override=workspace_override,
                approval_override=approval,
                backend_override=backend,
                base_url_override=base_url,
                model_override=model,
                timeout_override=timeout,
                cancel_event=cancel_event,
                return_metadata=True,
                suppress_trace=structured_output,
                save_session=save_session,
                resume_session=resume_session,
                session_output_path=session_output_path,
                max_steps=max_steps,
                no_memory=no_memory,
            ),
            run_timeout=run_timeout,
            session_output_path=session_output_path,
        )
    except Exception as exc:
        output = headless_exception_result(exc)
    if isinstance(output, HeadlessRunResult):
        exit_code = headless_exit_code(
            output.output,
            termination=output.termination,
            failing_tools=output.failing_tools,
        )
        write_headless_handoff_briefing_output(handoff_briefing_output_path, output, exit_code)
        if structured_output:
            write_headless_result_output(result_output_path, output, exit_code, output_format=result_artifact_format)
            print_headless_payload(output, exit_code, output_format=structured_format)
            raise typer.Exit(code=exit_code)
        write_headless_result_output(result_output_path, output, exit_code, output_format=result_artifact_format)
        if not quiet:
            print_raw(output.output)
        raise typer.Exit(code=exit_code)
    if structured_output:
        fallback_result = HeadlessRunResult(output=output)
        fallback_exit_code = headless_exit_code(output)
        write_headless_handoff_briefing_output(handoff_briefing_output_path, fallback_result, fallback_exit_code)
        write_headless_result_output(result_output_path, fallback_result, fallback_exit_code, output_format=result_artifact_format)
        print_headless_payload(
            fallback_result,
            fallback_exit_code,
            output_format=structured_format,
        )
        raise typer.Exit(code=fallback_exit_code)
    fallback_exit_code = headless_exit_code(output)
    fallback_result = HeadlessRunResult(output=output)
    write_headless_handoff_briefing_output(handoff_briefing_output_path, fallback_result, fallback_exit_code)
    write_headless_result_output(result_output_path, fallback_result, fallback_exit_code, output_format=result_artifact_format)
    if not quiet:
        print_raw(output)
    raise typer.Exit(code=fallback_exit_code)


@app.command("backends")
def backends(
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List registered LLM backend keys."""
    structured_format = structured_output_format(json_output, output_format)
    print_backend_list(json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("commands")
def commands_command(
    query: str | None = typer.Argument(None, help="Optional command or keyword filter, e.g. /workflow or memory."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List or search slash command catalog entries."""
    structured_format = structured_output_format(json_output, output_format)
    print_command_catalog(query, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("workflows")
def workflows_command(
    query: str | None = typer.Argument(None, help="Optional workflow name or alias, e.g. headless, audit, commit."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List or inspect practical workflow recipes."""
    structured_format = structured_output_format(json_output, output_format)
    print_workflow_catalog(query, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("tools")
def tools_command(
    query: str | None = typer.Argument(None, help="Optional tool, risk, or keyword filter, e.g. git, YELLOW, memory."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for tool discovery."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List or search available agent tools and risk metadata."""
    workspace_path = resolve_headless_workspace(workspace) or Settings().workspace
    registry = ToolRegistry(builtin_tools(workspace_path, NullMemoryClient()))
    structured_format = structured_output_format(json_output, output_format)
    print_tool_catalog(registry, query, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("infra")
def infra_command(
    map_key: str = typer.Argument("all", help="Map to read: all, quick, project, resource, home, vps, or resource-bundle."),
    per_file_chars: int = typer.Option(5000, "--per-file-chars", min=100, help="Maximum characters to read from each selected source."),
    max_chars: int = typer.Option(14000, "--max-chars", min=500, help="Maximum characters in the final context payload."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Read Maki's project/resource/home-AI/VPS maps as read-only context."""
    structured_format = structured_output_format(json_output, output_format)
    try:
        payload = infra_payload(map_key, per_file_chars=per_file_chars, max_chars=max_chars)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    print_infra_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("command-plan")
def command_plan_command(
    command: str = typer.Argument(..., help="Shell command string to classify without executing."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for compose-file discovery."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 after printing the payload when blockers are present."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Classify a shell command against agentX command policy without executing it."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = command_plan_payload(settings, command)
    structured_format = structured_output_format(json_output, output_format)
    print_command_plan_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(command_plan_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("tool-plan")
def tool_plan_command(
    tool: str = typer.Argument(..., help="Tool name or alias to classify without executing."),
    args_json: str = typer.Option("{}", "--args-json", "--args", help="Tool args as a JSON object string."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for path/compose checks."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 after printing the payload when blockers are present."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Classify an agentX tool call and args without executing it."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = tool_plan_payload(settings, tool, args_json)
    structured_format = structured_output_format(json_output, output_format)
    print_tool_plan_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(tool_plan_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("config")
def config_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for config resolution."),
    namespace: str | None = typer.Option(None, "--namespace", help="Override namespace shown in the payload."),
    mode: str | None = typer.Option(None, "--mode", help="Override mode shown in the payload."),
    approval: str | None = typer.Option(None, "--approval", help="Override approval mode shown in the payload."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Show resolved agentX configuration without live probes."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    project_config = load_project_config(settings.workspace)
    resolved_namespace = namespace or project_config.namespace or "project:agentX"
    resolved_mode = mode or project_config.mode or "chat"
    if resolved_mode == "ask":
        resolved_mode = "agent"
    approval_mode = normalize_approval_mode(approval or project_config.approval or ApprovalMode.ASK.value).value
    payload = config_payload(
        settings,
        namespace=resolved_namespace,
        mode=resolved_mode,
        approval=approval_mode,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_config_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("init")
def init_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for project profiling."),
    namespace: str | None = typer.Option(None, "--namespace", help="Override namespace shown in the payload."),
    write_memory: bool = typer.Option(False, "--write-memory", help="Write the generated project profile to Memory Hall."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Scan the workspace and optionally write a project profile to memory."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    project_config = load_project_config(settings.workspace)
    resolved_namespace = namespace or project_config.namespace or "project:agentX"
    memory_result = None
    if write_memory:
        if (settings.memory_backend or "memhall").lower() == "amh":
            from agentx.memory_hall import AmhClient

            memory: MemoryHallClient | NullMemoryClient = AmhClient(
                store=settings.memory_amh_store,
                store_path=settings.memory_amh_path,
            )
        else:
            memory = MemoryHallClient(
                base_url=settings.memory_hall_url,
                token=settings.memory_hall_token,
            )
        tools = ToolRegistry(builtin_tools(settings.workspace, memory))
        profile = build_project_profile(settings.workspace, resolved_namespace)
        result = tools.run(
            "memory_write",
            {
                "content": profile,
                "namespace": resolved_namespace,
                "tier": "human_confirmed",
                "memory_type": "fact",
            },
        )
        memory_result = {"ok": result.ok, "content": result.content[:1000]}
    payload = init_payload(
        settings,
        namespace=resolved_namespace,
        write_memory=write_memory,
        memory_result=memory_result,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_init_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("capabilities")
def capabilities_command(
    query: str | None = typer.Argument(None, help="Optional capability filter, e.g. verify, tasks, headless, schema name."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List machine-readable top-level CLI capabilities for runners."""
    structured_format = structured_output_format(json_output, output_format)
    print_capabilities(query, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("sessions")
def sessions_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for session discovery."),
    limit: int = typer.Option(10, "--limit", min=1, help="Maximum number of sessions to return."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List saved session transcripts."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = sessions_payload(settings, limit=limit)
    structured_format = structured_output_format(json_output, output_format)
    print_sessions_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("artifacts")
def artifacts_command(
    root: str = typer.Argument(".agentx/runs", help="Workspace-relative artifact root or a single artifact bundle directory."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for artifact discovery."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of artifact bundles to return."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List saved headless artifact bundles for external runners."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = artifacts_payload(settings, root=root, limit=limit)
    structured_format = structured_output_format(json_output, output_format)
    print_artifacts_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("approvals")
def approvals_command(
    session: str = typer.Argument("latest", help="Transcript name, file name, or latest."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for session discovery."),
    denied_only: bool = typer.Option(False, "--denied", help="Only return denied approval receipts."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of approval receipts to return."),
    fail_on_denied: bool = typer.Option(False, "--fail-on-denied", help="Exit 1 when returned receipts include a denied approval."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List approval receipts from saved transcripts for audit automation."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = approvals_payload(settings, session=session, limit=limit, denied_only=denied_only)
    structured_format = structured_output_format(json_output, output_format)
    print_approvals_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=approvals_exit_code(payload, fail_on_denied=fail_on_denied))


@app.command("traces")
def traces_command(
    session: str = typer.Argument("latest", help="Transcript name, file name, or latest."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for trace discovery."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of recent events to include."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Summarize transcript events, tools, approvals, and error-like records."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = traces_payload(settings, session=session, limit=limit)
    structured_format = structured_output_format(json_output, output_format)
    print_traces_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("diff")
def diff_command(
    path: str | None = typer.Argument(None, help="Optional workspace-relative path to diff."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for diff inspection."),
    staged: bool = typer.Option(False, "--staged", help="Inspect staged changes instead of the worktree diff."),
    patch: bool = typer.Option(False, "--patch", help="Include the git patch text in the payload."),
    max_patch_chars: int = typer.Option(20000, "--max-patch-chars", min=0, help="Maximum patch characters to include."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Summarize git diff for external runners without mutating the index."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = diff_payload(
        settings,
        path=path,
        staged=staged,
        include_patch=patch,
        max_patch_chars=max_patch_chars,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_diff_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("patch-check")
def patch_check_command(
    patch_file: str = typer.Argument(..., help="Workspace-relative patch file to validate."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for patch inspection."),
    timeout: int = typer.Option(20, "--timeout", min=1, help="git apply check timeout in seconds."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 when patch blockers are present."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Validate a workspace patch file without applying it."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = patch_check_payload(settings, patch_file=patch_file, timeout=timeout)
    structured_format = structured_output_format(json_output, output_format)
    print_patch_check_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=patch_check_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("tasks")
def tasks_command(
    status: str = typer.Argument("all", help="Task status filter: all, active, pending, in_progress, done, or blocked."),
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for task discovery."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List project tasks from .agentx/tasks.json."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = tasks_payload(settings, status_filter=status)
    structured_format = structured_output_format(json_output, output_format)
    print_tasks_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("verify")
def verify_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for verification."),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Per-command timeout in seconds."),
    fail_on_error: bool = typer.Option(False, "--fail-on-error", help="Exit 1 when any verification command fails."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Run default project verification commands and print an audit payload."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = verify_payload(settings, timeout=timeout)
    structured_format = structured_output_format(json_output, output_format)
    print_verify_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=verify_exit_code(payload, fail_on_error=fail_on_error))


@app.command("review")
def review_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for review inspection."),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Per-verification-command timeout in seconds."),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip verification commands and only summarize review posture."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 when blockers prevent commit readiness."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Run deterministic read-only review gate: diff summary plus verification posture."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = review_payload(settings, timeout=timeout, run_verify=not skip_verify)
    structured_format = structured_output_format(json_output, output_format)
    print_review_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=review_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("commit-plan")
def commit_plan_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for commit planning."),
    message: str | None = typer.Option(None, "--message", "-m", help="Proposed commit message; required for ready_to_commit=true."),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Per-verification-command timeout in seconds."),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip verification commands and only summarize commit posture."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 when blockers prevent commit readiness."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Print a read-only commit plan without staging, committing, or pushing."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = commit_plan_payload(
        settings,
        message=message,
        timeout=timeout,
        run_verify=not skip_verify,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_commit_plan_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=commit_plan_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("gate")
def gate_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for gate inspection."),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Per-verification-command timeout in seconds."),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip verification commands inside the review gate."),
    skip_doctor: bool = typer.Option(False, "--skip-doctor", help="Skip static doctor checks."),
    skip_approvals: bool = typer.Option(False, "--skip-approvals", help="Skip latest approval-denial audit."),
    approvals_limit: int = typer.Option(20, "--approvals-limit", min=1, help="Maximum approval receipts to inspect."),
    fail_on_blocker: bool = typer.Option(False, "--fail-on-blocker", help="Exit 1 when gate blockers are present."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Run a deterministic aggregate gate for runner handoff and commit readiness."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = gate_payload(
        settings,
        timeout=timeout,
        run_verify=not skip_verify,
        run_doctor=not skip_doctor,
        run_approvals=not skip_approvals,
        approvals_limit=approvals_limit,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_gate_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=gate_exit_code(payload, fail_on_blocker=fail_on_blocker))


@app.command("next")
def next_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for next-step planning."),
    artifacts_root: str = typer.Option(".agentx/runs", "--artifacts-root", help="Workspace-relative artifact root to inspect."),
    artifacts_limit: int = typer.Option(5, "--artifacts-limit", min=1, help="Maximum artifact bundles to inspect."),
    approvals_limit: int = typer.Option(20, "--approvals-limit", min=1, help="Maximum denied approval receipts to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Recommend the next runner command from local repo state."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    payload = next_payload(
        settings,
        artifacts_root=artifacts_root,
        artifacts_limit=artifacts_limit,
        approvals_limit=approvals_limit,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_next_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("inspect")
def inspect_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for inspection."),
    namespace: str | None = typer.Option(None, "--namespace", help="Override namespace shown in the payload."),
    mode: str | None = typer.Option(None, "--mode", help="Override mode shown in the payload."),
    approval: str | None = typer.Option(None, "--approval", help="Override approval mode shown in the payload."),
    sessions_limit: int = typer.Option(5, "--sessions-limit", min=1, help="Maximum number of session summaries to include."),
    approvals_limit: int = typer.Option(20, "--approvals-limit", min=1, help="Maximum number of approval receipts to include."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Print a read-only aggregate preflight bundle for external runners."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    project_config = load_project_config(settings.workspace)
    resolved_namespace = namespace or project_config.namespace or "project:agentX"
    resolved_mode = mode or project_config.mode or "chat"
    if resolved_mode == "ask":
        resolved_mode = "agent"
    approval_mode = normalize_approval_mode(approval or project_config.approval or ApprovalMode.ASK.value).value
    payload = inspect_payload(
        settings,
        namespace=resolved_namespace,
        mode=resolved_mode,
        approval=approval_mode,
        sessions_limit=sessions_limit,
        approvals_limit=approvals_limit,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_inspect_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("status")
def status_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for status resolution."),
    namespace: str | None = typer.Option(None, "--namespace", help="Override namespace shown in the payload."),
    mode: str | None = typer.Option(None, "--mode", help="Override mode shown in the payload."),
    approval: str | None = typer.Option(None, "--approval", help="Override approval mode shown in the payload."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Show machine-readable workspace posture without network probes."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    project_config = load_project_config(settings.workspace)
    resolved_namespace = namespace or project_config.namespace or "project:agentX"
    resolved_mode = mode or project_config.mode or "chat"
    if resolved_mode == "ask":
        resolved_mode = "agent"
    approval_mode = normalize_approval_mode(approval or project_config.approval or ApprovalMode.ASK.value).value
    payload = status_payload(
        settings,
        namespace=resolved_namespace,
        mode=resolved_mode,
        approval=approval_mode,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_status_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("doctor")
def doctor_command(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for doctor checks."),
    static: bool = typer.Option(False, "--static", help="Run only local static checks; skip Ollama and memory probes."),
    fail_on_error: bool = typer.Option(False, "--fail-on-error", help="Exit 1 when any doctor check fails."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Run agentX health checks for humans or automation."""
    settings = Settings(workspace=resolve_headless_workspace(workspace))
    if static:
        payload = doctor_payload(settings, live_probes=False)
    else:
        ollama = OllamaClient(
            base_url=settings.ollama_url,
            model=settings.model,
            timeout=settings.ollama_timeout,
        )
        try:
            if (settings.memory_backend or "memhall").lower() == "amh":
                from agentx.memory_hall import AmhClient

                memory: MemoryHallClient | NullMemoryClient = AmhClient(
                    store=settings.memory_amh_store,
                    store_path=settings.memory_amh_path,
                )
            else:
                memory = MemoryHallClient(
                    base_url=settings.memory_hall_url,
                    token=settings.memory_hall_token,
                )
            payload = doctor_payload(settings, memory=memory, ollama=ollama, live_probes=True)
        finally:
            ollama.close()
    structured_format = structured_output_format(json_output, output_format)
    print_doctor_payload(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")
    raise typer.Exit(code=doctor_exit_code(payload, fail_on_error=fail_on_error))


@app.command("models")
def models(
    workspace: str | None = typer.Option(None, "--workspace", "--cwd", help="Use a specific workspace directory for config resolution."),
    backend: str | None = typer.Option(None, "--backend", help="Override LLM backend."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override LLM backend base URL."),
    model: str | None = typer.Option(None, "--model", help="Override model used to initialize the backend client."),
    timeout: float | None = typer.Option(None, "--timeout", help="Override request timeout seconds."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """List models for the selected LLM backend."""
    payload = model_list_payload(
        workspace_override=resolve_headless_workspace(workspace),
        backend_override=backend,
        base_url_override=base_url,
        model_override=model,
        timeout_override=timeout,
    )
    structured_format = structured_output_format(json_output, output_format)
    print_model_list(payload, json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("version")
def version_command(
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Show agentX and Python versions."""
    structured_format = structured_output_format(json_output, output_format)
    print_version(json_output=structured_format != "plain", jsonl_output=structured_format == "jsonl")


@app.command("handoff-inspect")
def handoff_inspect(
    source: str = typer.Argument(..., help="Headless JSON/JSONL payload file to inspect, or '-' for stdin."),
    field: str | None = typer.Option(None, "--field", help="Print one takeover field, e.g. resume_command or recovery_checklist."),
    next_prompt: str | None = typer.Option(None, "--next-prompt", help="Replace the resume command placeholder with this prompt."),
    next_prompt_file: str | None = typer.Option(None, "--next-prompt-file", help="Replace the resume command placeholder with --prompt-file PATH."),
    resume_output_format: str | None = typer.Option(None, "--resume-output-format", help="Rewrite resume_command output mode: json or jsonl."),
    briefing_output: str | None = typer.Option(None, "--briefing-output", help="Write a Markdown handoff briefing inside the current workspace."),
    use_payload_exit_code: bool = typer.Option(
        False,
        "--use-payload-exit-code",
        help="Exit with the payload exit_code after printing takeover fields.",
    ),
    require_handoff: bool = typer.Option(
        False,
        "--require-handoff",
        help="Exit 1 unless the payload has needs_handoff=true and a resume_command.",
    ),
    require_schema_version: bool = typer.Option(
        False,
        "--require-schema-version",
        help=f"Exit 1 unless schema_version is {HEADLESS_PAYLOAD_SCHEMA_VERSION}.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Inspect a headless payload and print takeover fields."""
    structured_format = structured_output_format(json_output, output_format)
    if next_prompt and next_prompt_file:
        raise typer.BadParameter("use only one continuation source: --next-prompt or --next-prompt-file")
    payload = inspect_headless_handoff_payload(load_headless_payload_source(source))
    payload = apply_handoff_next_prompt(payload, next_prompt)
    payload = apply_handoff_next_prompt_file(payload, next_prompt_file)
    payload = apply_handoff_resume_output_format(payload, resume_output_format)
    write_handoff_briefing_output(resolve_handoff_briefing_output(Path.cwd(), briefing_output), payload)
    exit_code = handoff_inspect_exit_code(payload, use_payload_exit_code=use_payload_exit_code)
    if require_handoff and not handoff_takeover_ready(payload):
        exit_code = 1
    if require_schema_version and not handoff_schema_version_matches(payload):
        exit_code = 1
    if field:
        field_payload = handoff_inspect_field_payload(payload, field)
        if structured_format != "plain":
            print_structured_payload(field_payload, output_format=structured_format, event="handoff_inspect_field")
            raise typer.Exit(code=exit_code)
        sys.stdout.write(format_handoff_inspect_field_plain(field_payload))
        sys.stdout.write("\n")
        sys.stdout.flush()
        raise typer.Exit(code=exit_code)
    if structured_format != "plain":
        print_structured_payload(payload, output_format=structured_format, event="handoff_inspect")
        raise typer.Exit(code=exit_code)
    sys.stdout.write(format_handoff_inspect_plain(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()
    raise typer.Exit(code=exit_code)


@app.command("handoff-resume")
def handoff_resume(
    source: str = typer.Argument(..., help="Headless artifact directory or result JSON/JSONL payload file."),
    next_prompt: str | None = typer.Option(None, "--next-prompt", help="Replace the resume command placeholder with this prompt."),
    next_prompt_file: str | None = typer.Option(None, "--next-prompt-file", help="Replace the resume command placeholder with --prompt-file PATH."),
    resume_output_format: str | None = typer.Option(None, "--resume-output-format", help="Rewrite resume_command output mode: json or jsonl."),
    allow_missing_handoff: bool = typer.Option(False, "--allow-missing-handoff", help="Exit 0 even when the payload is not ready for takeover."),
    require_schema_version: bool = typer.Option(
        False,
        "--require-schema-version",
        help=f"Exit 1 unless schema_version is {HEADLESS_PAYLOAD_SCHEMA_VERSION}.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the command and argv that would be executed."),
    execute: bool = typer.Option(False, "--execute", help="Execute the generated resume command."),
    json_output: bool = typer.Option(False, "--json", help="Print a structured JSON result."),
    output_format: str = typer.Option("plain", "--output-format", help="Output format: plain, json, or jsonl."),
) -> None:
    """Print a resume command from a headless artifact bundle or result payload."""
    structured_format = structured_output_format(json_output, output_format)
    if next_prompt and next_prompt_file:
        raise typer.BadParameter("use only one continuation source: --next-prompt or --next-prompt-file")
    if dry_run and execute:
        raise typer.BadParameter("use only one resume action: --dry-run or --execute")

    raw_payload, default_prompt_file = load_handoff_resume_payload_source(source)
    payload = inspect_headless_handoff_payload(raw_payload)
    prompt_file = next_prompt_file
    if prompt_file is None and next_prompt is None and default_prompt_file is not None and default_prompt_file.is_file():
        prompt_file = str(default_prompt_file)
    payload = apply_handoff_next_prompt(payload, next_prompt)
    payload = apply_handoff_next_prompt_file(payload, prompt_file)
    payload = apply_handoff_resume_output_format(payload, resume_output_format)

    exit_code = 0
    if not allow_missing_handoff and not handoff_takeover_ready(payload):
        exit_code = 1
    if require_schema_version and not handoff_schema_version_matches(payload):
        exit_code = 1

    field_payload = handoff_resume_command_payload(payload)
    if dry_run:
        if structured_format != "plain":
            print_structured_payload(field_payload, output_format=structured_format, event="handoff_resume_dry_run")
            raise typer.Exit(code=exit_code)
        print_command_preview([str(item) for item in field_payload["argv"]])
        raise typer.Exit(code=exit_code)

    if execute:
        if exit_code != 0:
            if structured_format != "plain":
                print_structured_payload(field_payload, output_format=structured_format, event="handoff_resume")
            else:
                sys.stdout.write(format_handoff_inspect_field_plain(field_payload))
                sys.stdout.write("\n")
                sys.stdout.flush()
            raise typer.Exit(code=exit_code)
        argv = field_payload["argv"]
        if not isinstance(argv, list) or not argv:
            raise typer.BadParameter("resume command is empty")
        completed = subprocess.run([str(item) for item in argv], check=False)
        raise typer.Exit(code=int(completed.returncode))

    if structured_format != "plain":
        print_structured_payload(field_payload, output_format=structured_format, event="handoff_resume")
        raise typer.Exit(code=exit_code)
    sys.stdout.write(format_handoff_inspect_field_plain(field_payload))
    sys.stdout.write("\n")
    sys.stdout.flush()
    raise typer.Exit(code=exit_code)


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="Plain chat prompt for the Ollama model."),
) -> None:
    """Call Ollama directly without tool JSON mode."""
    settings = Settings()
    attachment_context, _ = build_attachment_context(prompt, settings.workspace)
    if attachment_context:
        prompt = f"{prompt}\n\n{attachment_context}"
    ollama, _, _ = build_runtime(settings)
    answer = ollama.chat(
        [
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona, model=settings.model)},
            {"role": "user", "content": prompt},
        ],
        json_mode=False,
    )
    print_raw(answer)


@app.command()
def shell(
    namespace: str | None = typer.Option(None, help="Default Memory Hall namespace."),
    mode: str | None = typer.Option(None, help="Start mode: chat or agent."),
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
) -> None:
    """Start an interactive agentX session."""
    global console
    settings = Settings()
    if max_steps is not None:
        settings = settings.with_updates(max_steps=max_steps)
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"
    mode = mode or project_config.mode or "chat"
    if mode == "ask":
        mode = "agent"

    # === 階段一：建立 ShellState（必須在任何 command 處理之前） ===
    state = ShellState(
        settings=settings,
        namespace=namespace,
        mode=mode,
    )

    # Phase A (MT22): 優先使用新多任務系統作為真相來源
    migrate_single_task_if_needed(settings.workspace)
    approval_policy = ApprovalPolicy(
        mode=normalize_approval_mode(project_config.approval) if project_config.approval else ApprovalMode.ASK
    )
    transcript = Transcript(settings.workspace, model=settings.model, namespace=namespace)

    def audit_approval(receipt: dict[str, object]) -> None:
        transcript.write("approval", receipt)

    ollama, memory, tools = build_runtime(
        settings,
        approval_policy=approval_policy,
        approval_audit=audit_approval,
    )

    # MT22 後：只使用新多任務清單（legacy 分支已移除）
    current_tasks = load_tasks(settings.workspace)
    task_summary = format_task_list_summary(current_tasks)

    if current_tasks:
        transcript.write("tasks", {"count": len(current_tasks), "summary": task_summary})
    compactor = LLMContextCompactor(ollama) if "gemma" in settings.model.lower() else None
    agent_session = AgentSession(
        settings=settings,
        ollama=ollama,
        tools=tools,
        namespace=namespace,
        trace=print_trace,
        compactor=compactor,
        memory=memory,
    )
    state.agent_session = agent_session
    state.memory = memory  # for hot-reload support (ACA amh backend)
    chat_messages = [
        {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona, model=settings.model)}
    ]
    history: list[tuple[str, str]] = []
    job_queue = PromptJobQueue()
    prompt_active = threading.Event()
    current_cancel = threading.Event()
    prompt_session: PromptSession[str] | None = None
    tui: AgentXTui | None = None
    original_console = console

    def status_line() -> str:
        pct = context_percent(state.settings, state.agent_session or agent_session, chat_messages)
        ap = approval_policy.mode.value if approval_policy else None
        return build_status_line(state.settings.model, state.plan_mode, pct, ap)

    def task_snapshot() -> tuple[list[dict], str]:
        tasks = load_tasks(state.settings.workspace)
        return tasks, format_task_list_summary(tasks)

    ui_mode = os.getenv("AGENTX_TUI", "1").lower()
    if sys.stdin.isatty() and ui_mode not in {"0", "false", "classic"}:
        tui = AgentXTui(
            command_catalog=COMMAND_CATALOG,
            status_text=status_line,
            full_screen=ui_mode in {"fullscreen", "full-screen"},
        )
        tui.start()
        console = Console(file=tui.writer, force_terminal=False, color_system=None, width=100)
    elif sys.stdin.isatty():
        prompt_session = PromptSession(
            completer=SlashCommandCompleter(catalog=COMMAND_CATALOG),
            complete_while_typing=True,
            erase_when_done=True,
            refresh_interval=0.2,
            bottom_toolbar=status_line,
        )

    def run_prompt_worker() -> None:
        nonlocal chat_messages
        while True:
            job = job_queue.get()
            if job is None:
                break
            queued_prompt = job.prompt
            current_cancel.clear()
            prompt_active.set()
            try:
                attachment_context, attachment_paths = build_attachment_context(
                    queued_prompt,
                    settings.workspace,
                )
                if attachment_context:
                    queued_prompt = f"{queued_prompt}\n\n{attachment_context}"
                    transcript.write("attachments", {"paths": attachment_paths})
                if state.mode == "agent":
                    history.append((state.mode, queued_prompt))
                    transcript.write("user", {"mode": state.mode, "content": queued_prompt})
                    agent_prompt = queued_prompt
                    if state.plan_mode:
                        agent_prompt = (
                            "你目前處於 PLAN MODE。請輸出結構化方案，不要呼叫任何工具。\n"
                            "請按照以下格式組織你的思考與回覆：\n"
                            "1. 目標（Goal）\n"
                            "2. 執行步驟（用編號清楚列出）\n"
                            "3. 每個步驟預計使用的工具或指令\n"
                            "4. 可能的風險、依賴或注意事項\n"
                            "5. 如何驗證成功\n\n"
                            "最後請用 final answer 總結完整方案。\n\n"
                            "當你認為規劃已經完整、足夠具體、可執行時，請在 final answer 的最後主動建議使用者輸入 `/execute` 來開始實際執行。\n\n"
                            "使用者任務："
                        ) + queued_prompt
                    answer = agent_session.ask(
                        agent_prompt,
                        namespace=namespace,
                        cancel_event=current_cancel,
                    )
                    transcript.write("assistant", {"mode": mode, "content": answer[:4000]})
                    if tui is not None:
                        print_raw(format_assistant_header())
                    print_block(answer)
                    continue

                history.append((state.mode, queued_prompt))
                transcript.write("user", {"mode": state.mode, "content": queued_prompt})
                chat_prompt = queued_prompt
                if state.plan_mode:
                    chat_prompt = "Plan only. Do not claim actions were performed. " + chat_prompt
                chat_messages.append({"role": "user", "content": chat_prompt})
                streamed: list[str] = []
                print_raw(format_assistant_header() if tui is not None else "")

                def on_delta(delta: str) -> None:
                    streamed.append(delta)
                    print_delta(delta)

                answer = ollama.chat(
                    chat_messages,
                    json_mode=False,
                    on_delta=on_delta,
                    cancel_event=current_cancel,
                )
                chat_messages.append({"role": "assistant", "content": answer})
                transcript.write("assistant", {"mode": mode, "content": answer[:4000]})
                if streamed:
                    print_raw("")
                else:
                    print_block(answer)
            except OllamaCancelledError:
                transcript.write("cancel", {"job": job.id, "prompt": queued_prompt})
                print_block(f"cancelled job #{job.id}")
            except Exception as exc:
                console.print(f"[red]prompt failed:[/red] {type(exc).__name__}: {escape(str(exc))}")
            finally:
                prompt_active.clear()
                current_cancel.clear()
                job_queue.complete_current()

    worker = threading.Thread(target=run_prompt_worker, name="agentx-prompt-worker", daemon=True)
    worker.start()

    def wait_for_prompt_worker() -> None:
        while job_queue.current is not None or job_queue.pending_count() > 0:
            threading.Event().wait(0.05)

    def stop_prompt_worker() -> None:
        job_queue.stop()
        worker.join(timeout=5)

    console.print(
        Panel.fit(
            Group(
                Text("agentX", style="bold cyan") + " v0.2.0  ·  本地 Ollama agent shell",
                "",
                f"model: [bold]{settings.model}[/bold]   |   mode: [bold]{mode}[/bold]   |   workspace: [bold]{settings.workspace}[/bold]",
                f"namespace: [bold]{namespace}[/bold]",
                "",
                "安全： [green]GREEN 自動[/green] ｜ [yellow]YELLOW 依策略[/yellow] ｜ [red]RED 受保護[/red]",
                "輸入 [bold cyan]/guide[/bold cyan] 快速導覽  ·  [bold cyan]/help[/bold cyan] 查看指令  ·  [bold cyan]/tools[/bold cyan] 查看工具",
                "",
                "[dim]功能強大，但控制權永遠在你手上。[/dim]",
            ),
            title="agentX shell",
            border_style="dim",
            padding=(0, 1),
        )
    )

    if should_show_guide_hint(settings.workspace):
        console.print()
        orientation = Panel(
            "[bold cyan]第一次使用這個 repo 的 agentX？[/bold cyan]\n"
            "  [cyan]/guide[/cyan]   60 秒掌握模式、工作流、安全與記憶\n"
            "  [cyan]/help[/cyan]    查看所有指令（已分類 + 安全提示）\n"
            "  [cyan]/tools[/cyan]   查看工具（清楚標示 GREEN/YELLOW/RED 風險）\n"
            "[dim]這個提示只會在本 repo 顯示一次；之後隨時可輸入 /guide。[/dim]",
            border_style="dim",
            padding=(0, 1),
        )
        console.print(orientation)
        mark_guide_hint_seen(settings.workspace)

    # === 階段一 Dispatch 相關函數 ===
    SLASH_HANDLERS: dict[str, Callable[[ShellState, str], None]] = {}

    def register_handler(command: str, handler: Callable[[ShellState, str], None]):
        SLASH_HANDLERS[command] = handler

    def handle_status(state: ShellState, prompt: str):
        """顯示目前 shell 狀態（含安全姿勢）— delegates to runtime handler."""
        def _status_panel(content: str, title: str) -> None:
            console.print(Panel(content, title=title, border_style="cyan"))

        _runtime_handlers.handle_status(
            state,
            prompt,
            transcript=transcript,
            emit=console.print,
            approval_mode=approval_policy.mode.value if approval_policy else "ask",
            message_count=len(chat_messages),
            format_status=format_plan_status,
            collect_aca_probe_info=_collect_aca_probe_info,
            emit_panel=_status_panel,
        )

    register_handler("/status", handle_status)

    def handle_help(state: ShellState, prompt: str):
        """顯示 slash command 說明 — delegates to runtime handler."""
        _runtime_handlers.handle_help(
            state,
            prompt,
            transcript=transcript,
            print_slash_help=print_slash_help,
        )

    register_handler("/help", handle_help)

    def handle_commands(state: ShellState, prompt: str):
        """列出或搜尋 slash command catalog — delegates to runtime handler."""
        _runtime_handlers.handle_commands(
            state,
            prompt,
            transcript=transcript,
            print_command_catalog=print_command_catalog,
        )

    register_handler("/commands", handle_commands)

    def handle_guide(state: ShellState, prompt: str):
        """顯示 60 秒快速導覽 — delegates to runtime handler."""
        _runtime_handlers.handle_guide(
            state,
            prompt,
            transcript=transcript,
            print_guide=print_guide,
            mark_guide_hint_seen=mark_guide_hint_seen,
        )

    register_handler("/guide", handle_guide)

    def handle_workflows(state: ShellState, prompt: str):
        """顯示常用 workflow recipe — delegates to runtime handler."""
        _runtime_handlers.handle_workflows(
            state,
            prompt,
            transcript=transcript,
            print_workflows=print_workflows,
        )

    register_handler("/workflows", handle_workflows)

    def handle_workflow(state: ShellState, prompt: str):
        """顯示單一 workflow recipe — delegates to runtime handler."""
        _runtime_handlers.handle_workflow(
            state,
            prompt,
            transcript=transcript,
            format_workflow_recipe=format_workflow_recipe,
            emit=print_tool_result,
        )

    register_handler("/workflow", handle_workflow)

    def handle_memory(state: ShellState, prompt: str):
        """查詢目前 namespace 的 Memory Hall 記憶（支援 /memory QUERY）— delegates."""
        _runtime_handlers.handle_memory(
            state,
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
            emit_usage=console.print,
        )

    register_handler("/memory", handle_memory)

    def handle_sessions(state: ShellState, prompt: str):
        """列出最近 transcript，可搭配 /resume — delegates to runtime handler."""
        _runtime_handlers.handle_sessions(
            state,
            prompt,
            transcript=transcript,
            print_sessions=print_sessions,
        )

    register_handler("/sessions", handle_sessions)

    def handle_transcript(state: ShellState, prompt: str):
        """顯示本輪 JSONL transcript 檔案路徑 — delegates to runtime handler."""
        _runtime_handlers.handle_transcript(
            state,
            prompt,
            transcript=transcript,
            emit=console.print,
        )

    register_handler("/transcript", handle_transcript)

    def handle_doctor(state: ShellState, prompt: str):
        """執行 doctor 檢查（Ollama、Memory Hall、git 等）"""
        transcript.write("slash_command", {"command": prompt})
        # Pass current posture info so /doctor can show vision-aligned safety summary
        print_doctor(
            state.settings,
            memory,
            ollama,
            approval_mode=approval_policy.mode.value if approval_policy else None,
            current_mode=state.mode,
        )

    register_handler("/doctor", handle_doctor)

    def handle_init(state: ShellState, prompt: str):
        """執行 /init：掃描 repo 並寫入 project profile 到 Memory Hall"""
        transcript.write("slash_command", {"command": prompt})
        output = run_init(state.settings, tools, state.namespace)
        transcript.write("init", {"content": output[:4000]})
        print_raw(output)

    register_handler("/init", handle_init)

    def handle_tools(state: ShellState, prompt: str):
        """列出目前可用的工具與說明 — delegates to runtime handler."""
        _runtime_handlers.handle_tools(
            state,
            prompt,
            transcript=transcript,
            tools=tools,
            print_tools=print_tool_catalog,
        )

    register_handler("/tools", handle_tools)

    def handle_context(state: ShellState, prompt: str):
        """顯示目前 agent context 使用情況 — delegates to runtime handler."""
        _runtime_handlers.handle_context(
            state,
            prompt,
            transcript=transcript,
            agent_session=state.agent_session or agent_session,
            chat_messages=chat_messages,
            print_context=print_context,
        )

    register_handler("/context", handle_context)

    def handle_compact(state: ShellState, prompt: str):
        """壓縮目前 agent session context"""
        transcript.write("slash_command", {"command": prompt})
        result = (state.agent_session or agent_session).compact()
        transcript.write("compact", {"result": result})
        print_raw(result)

    register_handler("/compact", handle_compact)

    def handle_history(state: ShellState, prompt: str):
        """顯示本輪 shell 互動歷史 — delegates to runtime handler."""
        _runtime_handlers.handle_history(
            state,
            prompt,
            transcript=transcript,
            history=history,
            print_history=print_history,
        )

    register_handler("/history", handle_history)

    def handle_jobs(state: ShellState, prompt: str):
        """顯示目前 jobs 佇列狀態 — delegates to runtime handler."""
        _runtime_handlers.handle_jobs(
            state,
            prompt,
            transcript=transcript,
            job_queue=job_queue,
            print_jobs=print_jobs,
        )

    register_handler("/jobs", handle_jobs)

    def handle_learn(state: ShellState, prompt: str):
        """觸發自我學習 reflection，產生改善提案（proposal-only，不自動修改核心）。參考 AGENTX.md 自修改協議。"""
        transcript.write("slash_command", {"command": prompt})
        if not hasattr(state, "agent_session") or state.agent_session is None:
            print_raw("No active agent session for learning.")
            return
        try:
            learnings = state.agent_session.reflect_and_learn()
            if learnings:
                print_raw(f"Generated {len(learnings)} learning proposals. Check .agentx/learning/proposals/ and review/approve before applying (per AGENTX.md Self-Improvement Protocol + ai-tetsu proposal gate).")
                for proposal in learnings:
                    print_raw(f"  - {proposal['id']}: {proposal['title']} ({proposal['type']}) status={proposal.get('status')}")
            else:
                print_raw("No new learning proposals generated (or learning disabled).")
        except Exception as e:
            print_raw(f"Learning reflection failed (safe): {e}")

    register_handler("/learn", handle_learn)

    def handle_cancel(state: ShellState, prompt: str):
        """取消 queued 或 current job"""
        value = prompt.removeprefix("/cancel").strip() or None
        transcript.write("slash_command", {"command": prompt})
        print_raw(cancel_jobs(job_queue, value, current_cancel))

    register_handler("/cancel", handle_cancel)

    def handle_clear(state: ShellState, prompt: str):
        """清空目前 shell 上下文（不影響 tasks）"""
        nonlocal chat_messages
        if state.agent_session:
            state.agent_session.clear_context()
        chat_messages[:] = [
            {
                "role": "system",
                "content": build_chat_system_prompt(state.settings.workspace, state.settings.persona, model=state.settings.model),
            }
        ]
        transcript.write("slash_command", {"command": prompt})
        console.print("cleared")

    register_handler("/clear", handle_clear)

    def handle_handoff(state: ShellState, prompt: str):
        """寫入 Memory Hall 交接摘要"""
        note = prompt.removeprefix("/handoff").strip() or None
        fresh_tasks, fresh_task_summary = task_snapshot()
        message = write_handoff(
            tools,
            settings=state.settings,
            namespace=state.namespace,
            mode=state.mode,
            history=history,
            transcript=transcript,
            tasks=fresh_tasks,
            note=note,
            task_summary=fresh_task_summary,
        )
        transcript.write("handoff", {"auto": False, "note": note, "result": message})
        print_raw(message)

    register_handler("/handoff", handle_handoff)

    def handle_resume(state: ShellState, prompt: str):
        """從 transcript 恢復上下文"""
        nonlocal chat_messages
        name = prompt.removeprefix("/resume").strip() or "latest"
        resume_path = find_transcript(state.settings.workspace, name, exclude=transcript.path)
        if resume_path is None:
            console.print(f"transcript not found: {name}")
            return
        summary = summarize_transcript(resume_path)
        if state.agent_session:
            state.agent_session.messages.append({"role": "system", "content": summary})
        chat_messages.append({"role": "system", "content": summary})
        transcript.write("resume", {"source": str(resume_path), "summary": summary[:2000]})
        print_raw(resume_loaded_message(resume_path, summary))

    register_handler("/resume", handle_resume)

    def handle_files(state: ShellState, prompt: str):
        """列出 repo 檔案（預設目前 workspace）— delegates to runtime handler."""
        _runtime_handlers.handle_files(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/files", handle_files)

    def handle_read(state: ShellState, prompt: str):
        """讀取 repo 內指定檔案 — delegates to runtime handler."""
        _runtime_handlers.handle_read(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/read", handle_read)

    def handle_search(state: ShellState, prompt: str):
        """在 repo 內搜尋文字 — delegates to runtime handler."""
        _runtime_handlers.handle_search(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/search", handle_search)

    def handle_find(state: ShellState, prompt: str):
        """依 keyword 檢索檔名/路徑與內容 — delegates to runtime handler."""
        _runtime_handlers.handle_find(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/find", handle_find)

    def handle_where(state: ShellState, prompt: str):
        """依 topic 定位可能檔案 — delegates to runtime handler."""
        _runtime_handlers.handle_where(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/where", handle_where)

    def handle_infra(state: ShellState, prompt: str):
        """讀取專案地圖與家庭 AI / VPS 資源地圖 — delegates to runtime handler."""
        _runtime_handlers.handle_infra(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/infra", handle_infra)

    def handle_intent(state: ShellState, prompt: str):
        """把自然語言需求整理成可執行 brief — delegates to runtime handler."""
        _runtime_handlers.handle_intent(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/intent", handle_intent)

    def handle_plan_task(state: ShellState, prompt: str):
        """把自然語言需求拆成 task checklist — delegates to runtime handler."""
        raw = prompt.removeprefix("/plan-task").strip()
        if raw.startswith("--apply "):
            text = raw.removeprefix("--apply ").strip()
            output = apply_plan_task(state.settings.workspace, text)
            transcript.write(
                "slash_command",
                {"command": "/plan-task", "apply": True, "text": text, "content": output[:4000]},
            )
            print_tool_result(output)
            return
        _runtime_handlers.handle_plan_task(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/plan-task", handle_plan_task)

    def handle_grep(state: ShellState, prompt: str):
        """在指定 path 內搜尋內容 — delegates to runtime handler."""
        _runtime_handlers.handle_grep(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/grep", handle_grep)

    def handle_fetch(state: ShellState, prompt: str):
        """讀取指定外部網頁文字 — delegates to runtime handler."""
        _runtime_handlers.handle_fetch(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/fetch", handle_fetch)

    def handle_attach(state: ShellState, prompt: str):
        """附加檔案內容到上下文"""
        nonlocal chat_messages
        attachment_text = prompt.removeprefix("/attach ").strip()
        attachment_context, attachment_paths = build_attachment_context(
            attachment_text,
            state.settings.workspace,
        )
        if not attachment_context:
            print_raw("no readable attachment found")
            return
        if state.agent_session:
            state.agent_session.messages.append({"role": "system", "content": attachment_context})
        chat_messages.append({"role": "system", "content": attachment_context})
        transcript.write("attachments", {"paths": attachment_paths})
        print_raw("attached files:\n" + "\n".join(attachment_paths))

    register_handler("/attach", handle_attach)

    def handle_git(state: ShellState, prompt: str):
        """顯示 git status — delegates to runtime handler."""
        _runtime_handlers.handle_git(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/git", handle_git)

    def handle_diff(state: ShellState, prompt: str):
        """顯示 git diff，可指定單一檔案 — delegates to runtime handler."""
        _runtime_handlers.handle_diff(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/diff", handle_diff)

    def handle_stage(state: ShellState, prompt: str):
        """逐檔 stage 指定檔案 — delegates to runtime handler."""
        _runtime_handlers.handle_stage(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/stage", handle_stage)

    def handle_unstage(state: ShellState, prompt: str):
        """逐檔 unstage 指定檔案 — delegates to runtime handler."""
        _runtime_handlers.handle_unstage(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/unstage", handle_unstage)

    def handle_push(state: ShellState, prompt: str):
        """推送目前 branch — delegates to runtime handler."""
        _runtime_handlers.handle_push(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/push", handle_push)

    def handle_apply(state: ShellState, prompt: str):
        """套用 patch 檔案（YELLOW 工具，會經過 approval gate）"""
        path = prompt.removeprefix("/apply ").strip()
        # 基本安全檢查（與舊邏輯一致）
        patch_path = (state.settings.workspace / path).resolve()
        if state.settings.workspace != patch_path and state.settings.workspace not in patch_path.parents:
            print_raw("patch path escapes workspace")
            return
        if not patch_path.is_file():
            print_raw(f"patch file not found: {path}")
            return
        patch = patch_path.read_text(encoding="utf-8", errors="replace")
        result = tools.run("apply_patch", {"patch": patch})
        transcript.write(
            "tool",
            {"command": "/apply", "path": path, "ok": result.ok, "content": result.content[:2000]},
        )
        print_tool_result(result.content if result.ok else f"patch failed: {result.content}")

    register_handler("/apply", handle_apply)

    def handle_review(state: ShellState, prompt: str):
        """收集 git diff + 測試結果，請模型做 findings-first review（繁體中文）"""
        transcript.write("slash_command", {"command": prompt})
        output = run_review(ollama, tools)
        transcript.write("review", {"content": output[:4000]})
        print_raw(output)

    register_handler("/review", handle_review)

    def handle_commit(state: ShellState, prompt: str):
        """執行 /commit：跑測試、逐檔 stage、中文 commit 並 push"""
        message = prompt.removeprefix("/commit").strip() or None
        transcript.write("slash_command", {"command": prompt})
        output = run_commit_flow(state.settings, tools, message)
        transcript.write("commit", {"message": message, "content": output[:4000]})
        print_raw(output)

    register_handler("/commit", handle_commit)

    def handle_approval(state: ShellState, prompt: str):
        """查看或切換 YELLOW 工具的 approval policy（含 aliases）"""
        if prompt == "/approval":
            transcript.write("slash_command", {"command": prompt})
            print_approval(approval_policy)
            return

        mode_value = prompt.removeprefix("/approval ").strip()
        try:
            approval_policy.mode = normalize_approval_mode(mode_value)
        except ValueError:
            print_raw("usage: /approval ask|auto|off|strict|auto-approve|deny")
            return
        transcript.write("slash_command", {"command": prompt, "approval": approval_policy.mode.value})
        print_approval(approval_policy)

    register_handler("/approval", handle_approval)

    def handle_plan(state: ShellState, prompt: str):
        """切換 plan mode — delegates to importable runtime handler."""
        _runtime_handlers.handle_plan(
            state,
            prompt,
            transcript=transcript,
            emit=console.print,
            format_status=format_plan_status,
        )

    register_handler("/plan", handle_plan)

    def handle_execute(state: ShellState, prompt: str):
        """從 plan 模式切換至執行模式 — delegates to importable runtime handler."""
        _runtime_handlers.handle_execute(
            state,
            prompt,
            transcript=transcript,
            chat_messages=chat_messages,
            emit=console.print,
        )

    register_handler("/execute", handle_execute)

    def handle_mode(state: ShellState, prompt: str):
        """切換 chat / agent 模式 — delegates to importable runtime handler."""
        _runtime_handlers.handle_mode(
            state,
            prompt,
            transcript=transcript,
            emit=console.print,
            emit_error=print_raw,
        )

    register_handler("/mode", handle_mode)

    def handle_models(state: ShellState, prompt: str):
        """列出目前 Ollama 可用模型"""
        transcript.write("slash_command", {"command": prompt})
        try:
            models = ollama.list_models()
        except Exception as exc:
            print_raw(f"models failed: {type(exc).__name__}: {exc}")
            return
        print_tool_result("\n".join(models))

    register_handler("/models", handle_models)

    def handle_model(state: ShellState, prompt: str):
        """查看或切換目前使用的模型"""
        if prompt == "/model":
            transcript.write("slash_command", {"command": prompt, "model": state.settings.model})
            console.print(f"model={state.settings.model}")
            console.print("usage: /model MODEL")
            console.print("example: /model gemma4:31b")
            console.print("list models: /models")
            return

        # /model <name>
        model = prompt.removeprefix("/model ").strip()
        if not model:
            print_raw("usage: /model gemma4:31b")
            return

        new_settings = state.update_settings(model=model)

        # 切換模型需要重建 LLM client（外部相依）
        # Use registry so AGENTX_BACKEND=llama_cpp continues to work.
        register_builtin_backends()
        import os as _os
        backend = _os.getenv("AGENTX_BACKEND", "ollama").lower()
        nonlocal ollama
        ollama = get_llm_client(
            backend,
            base_url=new_settings.ollama_url,
            model=new_settings.model,
            timeout=new_settings.ollama_timeout,
        )
        if state.agent_session:
            state.agent_session.ollama = ollama

        transcript.write("slash_command", {"command": prompt, "model": new_settings.model})
        console.print(f"model={new_settings.model}")

    register_handler("/model", handle_model)

    def handle_persona(state: ShellState, prompt: str):
        """查看或切換人格（default / tutor）"""
        if prompt == "/persona":
            transcript.write("slash_command", {"command": prompt, "persona": state.settings.persona})
            console.print(f"persona={state.settings.persona}")
            print_raw(list_personas())
            return

        value = prompt.removeprefix("/persona ").strip()
        try:
            persona = normalize_persona(value)
        except ValueError as exc:
            print_raw(str(exc))
            return

        state.set_persona(persona)

        if state.agent_session:
            state.agent_session.clear()

        nonlocal chat_messages
        chat_messages = [
            {
                "role": "system",
                "content": build_chat_system_prompt(state.settings.workspace, state.settings.persona, model=state.settings.model),
            }
        ]

        transcript.write("slash_command", {"command": prompt, "persona": state.settings.persona})
        console.print(f"persona={state.settings.persona}")

    register_handler("/persona", handle_persona)

    def handle_remember(state: ShellState, prompt: str):
        """寫入 Memory Hall"""
        content = prompt.removeprefix("/remember ").strip()
        if not content:
            print_raw("usage: /remember 要寫入 Memory Hall 的內容")
            return
        # /remember is explicit human input → human_confirmed (ACA L2 Trust)
        result = tools.run(
            "memory_write",
            {"content": content, "namespace": state.namespace, "tier": "human_confirmed", "memory_type": "note"},
        )
        transcript.write("tool", {"command": "/remember", "ok": result.ok, "content": content})
        if result.ok:
            console.print(f"remembered in {state.namespace} (human_confirmed)")
        else:
            print_raw(f"remember failed: {result.content}")

    register_handler("/remember", handle_remember)

    def handle_run(state: ShellState, prompt: str):
        """執行 allowlist 指令 — delegates to runtime handler."""
        _runtime_handlers.handle_run(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/run", handle_run)

    def handle_test(state: ShellState, prompt: str):
        """執行固定 allowlist 驗證 — delegates to runtime handler."""
        _runtime_handlers.handle_test(
            prompt,
            tools=tools,
            transcript=transcript,
            emit=print_tool_result,
        )

    register_handler("/test", handle_test)

    def handle_config(state: ShellState, prompt: str):
        """查看或設定專案 config"""
        if prompt == "/config":
            transcript.write("slash_command", {"command": prompt})
            print_config(state.settings, state.namespace, state.mode, approval_policy, memory=getattr(state, "memory", None))
            return

        if prompt.startswith("/config set "):
            parts = prompt.split(maxsplit=3)
            if len(parts) != 4:
                print_raw("usage: /config set KEY VALUE")
                return
            _, _, key, value = parts
            try:
                updated = set_project_config(state.settings.workspace, key, value)
            except ValueError as exc:
                print_raw(str(exc))
                return
            transcript.write("slash_command", {"command": prompt, "config": key})
            console.print(f"config updated: {key}")
            print_raw(updated)

            if key in ("memory_backend", "memory_amh_store", "memory_amh_path"):
                # Hot-reload for ACA AmhClient so /memory etc take effect immediately
                project_config = load_project_config(state.settings.workspace)
                if (project_config.memory_backend or "memhall").lower() == "amh":
                    from agentx.memory_hall import AmhClient
                    new_memory = AmhClient(
                        store=project_config.memory_amh_store or "json",
                        store_path=project_config.memory_amh_path,
                    )
                else:
                    new_memory = MemoryHallClient(
                        base_url=state.settings.memory_hall_url,
                        token=state.settings.memory_hall_token,
                    )
                # Update in-memory settings so /status /config etc reflect new values
                state.update_settings(
                    memory_backend=project_config.memory_backend or state.settings.memory_backend,
                    memory_amh_store=project_config.memory_amh_store,
                    memory_amh_path=project_config.memory_amh_path,
                )
                # Patch the live tool instances (the ones bound to current tools registry)
                for mem_name in ("memory_search", "memory_write", "memory_tier_upgrade", "memory_audit"):
                    t = tools.get(mem_name)
                    if t is not None and hasattr(t, "memory"):
                        t.memory = new_memory
                state.memory = new_memory
                if state.agent_session is not None:
                    state.agent_session.memory = new_memory
                console.print("memory client hot-swapped (immediate effect for memory commands, no restart)")

            return

    register_handler("/config", handle_config)

    def handle_docker(state: ShellState, prompt: str):
        """Docker Compose 相關指令（部分需 approval）"""
        docker_args = parse_docker_prompt(prompt)
        if docker_args is None:
            print_raw("usage: /docker ps|build|up|logs [SERVICE]|down")
            return

        action = str(docker_args.pop("action"))
        try:
            command = docker_compose_command(
                state.settings.workspace,
                action,
                service=str(docker_args["service"]) if "service" in docker_args else None,
            )
        except Exception as exc:
            print_raw(f"docker command rejected: {type(exc).__name__}: {exc}")
            return

        print_command_preview(command)
        result = tools.run(f"docker_compose_{action}", docker_args)
        transcript.write(
            "tool",
            {
                "command": "/docker",
                "action": action,
                "args": docker_args,
                "ok": result.ok,
                "content": result.content[:4000],
            },
        )
        print_tool_result(result.content if result.ok else f"docker failed: {result.content}")

    register_handler("/docker", handle_docker)

    def handle_task(state: ShellState, prompt: str):
        """多任務清單管理（/task 複雜子命令）"""
        transcript.write("slash_command", {"command": prompt})
        value = prompt.removeprefix("/task ").strip() if prompt.startswith("/task ") else ""

        tasks = load_tasks(state.settings.workspace)

        # 顯示狀態（empty / status / list）— delegates to read-only runtime helper
        def _task_panel(content: str, title: str) -> None:
            console.print(Panel(content, title=title, border_style="cyan"))

        if _runtime_handlers.handle_task_readonly(
            value,
            tasks=tasks,
            format_summary=format_task_list_summary,
            emit_panel=_task_panel,
            emit=console.print,
        ):
            return

        # 新增任務
        if value.startswith("add "):
            desc = value.removeprefix("add ").strip()
            if desc:
                new_task = {
                    "id": get_next_task_id(tasks),
                    "description": desc[:200],
                    "status": "in_progress",
                    "notes": "",
                }
                tasks.append(new_task)
                save_tasks(state.settings.workspace, tasks)
                console.print(f"[green]已新增任務 #{new_task['id']}: {desc}[/green]")
            return

        # 更新任務
        if value.startswith("update "):
            parts = value.removeprefix("update ").strip().split(maxsplit=2)
            if len(parts) >= 2:
                try:
                    tid = int(parts[0])
                    new_status = parts[1]
                    new_notes = parts[2] if len(parts) > 2 else None

                    valid_status = {"pending", "in_progress", "done"}
                    if new_status not in valid_status:
                        console.print(f"[yellow]無效的 status '{new_status}'，允許值：{valid_status}[/yellow]")
                        return

                    found = False
                    for t in tasks:
                        if t["id"] == tid:
                            t["status"] = new_status
                            if new_notes is not None:
                                t["notes"] = new_notes[:500]
                            found = True
                            break

                    if found:
                        save_tasks(state.settings.workspace, tasks)
                        console.print(f"[green]已更新任務 #{tid}[/green]")
                    else:
                        console.print(f"[yellow]找不到任務 #{tid}[/yellow]")
                except ValueError:
                    console.print("[red]task id 必須是數字[/red]")
            return

        # 快速完成
        if value.startswith("done "):
            try:
                tid = int(value.removeprefix("done ").strip())
                found = False
                for t in tasks:
                    if t["id"] == tid:
                        t["status"] = "done"
                        found = True
                        break

                if found:
                    save_tasks(state.settings.workspace, tasks)
                    console.print(f"[green]已完成任務 #{tid}[/green]")
                else:
                    console.print(f"[yellow]找不到任務 #{tid}[/yellow]")
            except ValueError:
                console.print("[red]task id 必須是數字[/red]")
            return

        # 清空
        if value == "clear":
            save_tasks(state.settings.workspace, [])
            console.print("[yellow]已清空所有任務清單[/yellow]")
            return

        if value == "done":
            console.print("[yellow]請指定任務 id，例如：/task done 3[/yellow]")
            return

        # 相容舊用法：直接文字當成新增任務
        if value and not value.startswith(("add", "update", "done", "clear", "status", "list")):
            new_task = {
                "id": get_next_task_id(tasks),
                "description": value[:200],
                "status": "in_progress",
                "notes": "[來自 /task 舊式語法]",
            }
            tasks.append(new_task)
            save_tasks(state.settings.workspace, tasks)
            console.print(f"[green]已新增任務 #{new_task['id']}: {value}[/green]（建議之後用 /task add 或 /task update 管理）")
            return

    register_handler("/task", handle_task)

    # Dispatch 輔助：支援 exact match 與 prefix match（如 /memory foo、/remember bar）
    def _try_dispatch(p: str) -> bool:
        if p in SLASH_HANDLERS:
            SLASH_HANDLERS[p](state, p)
            return True
        # 由長到短比對 prefix（避免 /me 誤配 /memory）
        for cmd, handler in sorted(SLASH_HANDLERS.items(), key=lambda kv: -len(kv[0])):
            if p.startswith(cmd + " "):
                handler(state, p)
                return True
        return False

    try:
        while True:
            try:
                if tui is not None:
                    prompt = tui.prompt().strip()
                elif prompt_session is None:
                    prompt = typer.prompt("agentX").strip()
                else:
                    with patch_stdout(raw=True):
                        prompt = prompt_session.prompt("agentX: ").strip()
            except KeyboardInterrupt:
                interrupt_message = handle_keyboard_interrupt(job_queue, current_cancel)
                if interrupt_message is not None:
                    print_raw(f"\n{interrupt_message}")
                    continue
                wait_for_prompt_worker()
                if history and state.settings.auto_handoff:
                    fresh_tasks, fresh_task_summary = task_snapshot()
                    message = write_handoff(
                        tools,
                        settings=state.settings,
                        namespace=state.namespace,
                        mode=state.mode,
                        history=history,
                        transcript=transcript,
                        tasks=fresh_tasks,
                        task_summary=fresh_task_summary,
                    )
                    transcript.write("handoff", {"auto": True, "result": message})
                    print_raw(f"\n{message}")
                transcript.write("session_end", {"reason": "keyboard_interrupt", "forced": False})
                console.print("\nbye")
                break
            except EOFError:
                wait_for_prompt_worker()
                if history and state.settings.auto_handoff:
                    fresh_tasks, fresh_task_summary = task_snapshot()
                    message = write_handoff(
                        tools,
                        settings=state.settings,
                        namespace=state.namespace,
                        mode=state.mode,
                        history=history,
                        transcript=transcript,
                        tasks=fresh_tasks,
                        task_summary=fresh_task_summary,
                    )
                    transcript.write("handoff", {"auto": True, "result": message})
                    print_raw(f"\n{message}")
                transcript.write("session_end", {"reason": "eof", "forced": False})
                console.print("\nbye")
                break

            if not prompt:
                continue
            if prompt_session is not None:
                print_block(f"agentX: {prompt}")

            # 退出指令最高優先，永遠最先處理（避免 dispatch 重構或 job 等待導致「退不出來」）
            if prompt in {"/exit", "/quit"}:
                if current_cancel is not None:
                    current_cancel.set()  # 強制取消目前進行中的 agent 工作，讓 /exit 能真正退出
                job_queue.stop()  # 立即發送 sentinel 喚醒 worker thread，不阻塞使用者
                # 只在沒有進行中 job 時才嘗試 auto handoff，避免無限等待
                if not (job_queue.current is not None or job_queue.pending_count() > 0):
                    if history and state.settings.auto_handoff:
                        fresh_tasks, fresh_task_summary = task_snapshot()
                        message = write_handoff(
                            tools,
                            settings=state.settings,
                            namespace=state.namespace,
                            mode=state.mode,
                            history=history,
                            transcript=transcript,
                            tasks=fresh_tasks,
                            task_summary=fresh_task_summary,
                        )
                        transcript.write("handoff", {"auto": True, "result": message})
                        print_raw(message)
                transcript.write("session_end", {"reason": prompt, "forced": bool(job_queue.current is not None or job_queue.pending_count() > 0)})
                console.print("\nbye")
                break

            # Dispatch 機制 (階段一) — 支援帶參數指令
            if _try_dispatch(prompt):
                continue
            if prompt.startswith("/") and not prompt.startswith(("/jobs", "/cancel")):
                wait_for_prompt_worker()
                transcript.write(
                    "slash_command_unknown",
                    {"command": prompt, "suggestions": slash_command_suggestions(prompt)},
                )
                print_tool_result(format_unknown_slash_command(prompt))
                continue

            # Natural language trigger for execute when in plan mode
            if state.plan_mode and is_natural_execute_trigger(prompt):
                state.set_plan_mode(False)
                transcript.write("slash_command", {"command": "natural_execute", "original": prompt})

                execute_message = (
                    "使用者已透過自然語言要求開始執行。\n"
                    "規劃階段結束，現在切換至執行模式。請使用工具逐步完成方案。"
                )
                if state.agent_session:
                    state.agent_session.messages.append({"role": "system", "content": execute_message})
                chat_messages.append({"role": "system", "content": execute_message})

                console.print("已透過自然語言切換至執行模式。後續將可使用工具實際執行。")
                continue

            job = job_queue.submit(prompt)
            pending = job_queue.pending_count()
            if prompt_active.is_set() or pending > 1:
                console.print(f"[dim]queued job #{job.id}; pending={pending}[/dim]")
    finally:
        stop_prompt_worker()
        if tui is not None:
            tui.stop()
            console = original_console


if __name__ == "__main__":
    app()
