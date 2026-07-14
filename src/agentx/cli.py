from __future__ import annotations

import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import json
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
    command_catalog_payload,
    filtered_command_catalog_payload,
    format_unknown_slash_command,
    normalize_slash_command_topic,
    slash_command_help,
    slash_command_suggestions,
)
from agentx.context_compactor import LLMContextCompactor
from agentx.doctor import run_doctor
from agentx.git_workflow import build_commit_plan, commit_and_push
from agentx.intent import plan_task_items
from agentx.jobs import PromptJobQueue
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient, NullMemoryClient
from agentx.ollama import OllamaCancelledError, OllamaClient
from agentx.provider_registry import get_llm_client, list_registered_backends, LLMClient, register_builtin_backends
from agentx.persona import list_personas, normalize_persona
from agentx.project_config import load_project_config, set_project_config
from agentx.project_profile import build_project_profile
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
    DOCKER_COMPOSE_ACTIONS,
    ToolRegistry,
    builtin_tools,
    docker_compose_command,
    resolve_inside_workspace,
)
from agentx.transcript import (
    Transcript,
    find_transcript,
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
    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Start")
    table.add_column("Model")
    table.add_column("Namespace")
    table.add_column("Turns", justify="right")
    table.add_column("Approval", justify="right")
    table.add_column("Last")
    for path in list_transcripts(settings.workspace):
        overview = transcript_overview(path)
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
    payload = {
        "schema_version": HEADLESS_PAYLOAD_SCHEMA_VERSION,
        "output": result.output,
        "exit_code": exit_code,
        "termination": result.termination,
        "failing_tools": list(result.failing_tools),
        "stats": result.stats,
        "log_summary": log_summary,
        "session_path": result.session_path,
    }
    if result.phases:
        payload["phases"] = list(result.phases)
    return payload


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
            print_tools=print_tools,
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
