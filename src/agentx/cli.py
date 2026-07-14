from __future__ import annotations

import os
import re
import shlex
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
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
from agentx.approval import ApprovalMode, ApprovalPolicy, normalize_approval_mode
from agentx.attachments import extract_file_paths, format_attachment_context, read_attachments
from agentx.config import Settings
from agentx.context_compactor import LLMContextCompactor
from agentx.doctor import run_doctor
from agentx.git_workflow import build_commit_plan, commit_and_push
from agentx.jobs import PromptJobQueue
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaCancelledError, OllamaClient
from agentx.provider_registry import get_llm_client, LLMClient, register_builtin_backends
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
from agentx.tools import DOCKER_COMPOSE_ACTIONS, ToolRegistry, builtin_tools, docker_compose_command
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

SLASH_COMMANDS = [
    ("/help", "列出所有 slash command 與中文說明"),
    ("/guide", "60 秒快速導覽：模式選擇、常用工作流、安全與記憶"),
    ("/workflows", "列出實務工作流：理解、修改、測試、review、handoff"),
    ("/init", "掃描 repo 並寫入 project profile 到 Memory Hall"),
    ("/task [TEXT|status|list|add ...|update <id> ...|done <id>|clear]", "多任務清單管理（已統一為真相來源）"),
    ("/doctor", "檢查 Ollama、模型、Memory Hall、git、uv 狀態"),
    ("/config", "顯示目前 agentX 設定"),
    ("/config set KEY VALUE", "寫入 .agentx/config.toml"),
    ("/tools", "列出可用工具（已依 GREEN/YELLOW/RED 風險分組，符合安全視覺化）"),
    ("/context", "顯示目前 agent 上下文使用量與壓縮次數"),
    ("/compact", "壓縮目前 agent session 上下文，保留最近訊息摘要"),
    ("/history", "顯示本輪 shell 的簡短互動紀錄"),
    ("/jobs", "顯示目前執行中與排隊中的 prompt"),
    ("/cancel [JOB_ID|all]", "取消尚未執行的 queued prompt"),
    ("/sessions", "列出最近 transcript，可搭配 /resume"),
    ("/transcript", "顯示本輪 JSONL transcript 檔案路徑"),
    ("/handoff [TEXT]", "寫入 Memory Hall 交接摘要；未提供文字時自動整理本輪紀錄"),
    ("/resume [latest|FILE]", "從 JSONL transcript 載入最近上下文摘要"),
    ("/files [PATH]", "列出 repo 檔案，預設目前 workspace"),
    ("/read PATH", "讀取 repo 內指定檔案"),
    ("/attach PATH...", "把指定檔案內容加入本輪 context；支援拖曳路徑"),
    ("/find KEYWORD", "依 keyword 搜尋檔名/路徑與內容，並建議 /read 目標"),
    ("/where TOPIC", "依 topic 定位最可能的檔案位置，輸出 ranked /read 建議"),
    ("/infra [all|quick|project|resource|home|vps]", "讀取專案地圖、家庭 AI 設施與 VPS 資源地圖（read-only）"),
    ("/grep PATTERN [PATH]", "在指定 path 內做 rg 內容搜尋；預設整個 workspace"),
    ("/search PATTERN", "在 repo 內搜尋文字"),
    ("/fetch URL", "讀取指定外部網頁文字，會阻擋 localhost 與私有網段"),
    ("/git [status|branch|log [N]|show [REV]]", "顯示 allowlisted git 唯讀資訊"),
    ("/diff [PATH]", "顯示 git diff，可指定單一檔案"),
    ("/stage PATH...", "逐檔 stage 指定檔案；拒絕 .、glob、目錄與 workspace 外路徑"),
    ("/unstage PATH...", "逐檔 unstage 指定檔案，保留 worktree 修改"),
    ("/push", "推送目前 branch 到既有 upstream；不接受參數"),
    ("/apply PATCH_FILE", "套用 workspace 內 patch 檔，會先要求 approval"),
    ("/approval [ask|auto|off|strict|auto-approve|deny]", "查看或切換 YELLOW 工具 approval policy"),
    ("/memory QUERY", "查詢目前 namespace 的 Memory Hall 記憶"),
    ("/run COMMAND", "執行固定 allowlist 命令"),
    ("/docker [ps|build|up|logs|down]", "執行 workspace 內 Docker Compose allowlist 指令"),
    ("/test", "執行固定 allowlist 驗證：ruff check 與 pytest"),
    ("/review", "收集 git diff 與測試結果，輸出 findings-first review"),
    ("/commit [MESSAGE]", "跑測試後逐檔 stage、中文 commit 並 push"),
    ("/plan", "切換 plan 模式；plan 模式只討論方案，不使用工具"),
    ("/execute", "從 plan 模式切換至執行模式，後續將可使用工具實際執行方案"),
    ("/mode chat", "切換到純聊天模式，不使用工具，速度較快"),
    ("/mode ask", "切換到單次任務語意的 agent 工具模式，同 /mode agent"),
    ("/mode agent", "切換到 agent 工具模式，可使用 repo / git / Memory Hall 工具"),
    ("/models", "列出 Ollama 目前可用模型"),
    ("/model [MODEL]", "查看或切換 Ollama 模型，例如 /model gemma4:31b"),
    ("/persona [default|tutor|gemma4]", "查看或切換人格設定；tutor 是家庭教師，gemma4 是弱模型專用（小步驟+嚴格驗證）"),
    ("/remember TEXT", "把指定內容寫入目前 Memory Hall namespace"),
    ("/status", "顯示目前模型、模式、namespace、訊息數與粗估 context tokens"),
    ("/clear", "清空目前 shell session 上下文，並重新載入 repo 與 Memory Hall context"),
    ("/exit", "離開 agentX shell"),
    ("/quit", "離開 agentX shell，同 /exit"),
]

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
    ("提交收尾", "/review  →  /commit 中文訊息"),
]


def print_trace(message: str) -> None:
    console.print(f"[dim][trace] {escape(message)}[/dim]")


def slash_command_hint() -> Columns:
    """回傳用 Columns 自動排版的指令列表（更漂亮）"""
    commands = [command for command, _ in SLASH_COMMANDS]
    # 轉成帶樣式的 Text
    texts = [Text(cmd, style="cyan") for cmd in commands]
    # equal=True 讓每欄寬度一致，expand=True 讓它盡量填滿
    return Columns(texts, equal=True, expand=True, column_first=True)


def print_slash_help() -> None:
    """Print slash commands grouped by category with risk/safety hints.

    This is a direct step toward the vision in Image 02 & 03:
    - Clear mental models and discoverability
    - Risk awareness baked into the help experience
    """
    # Category definitions (vision-aligned grouping)
    categories = [
        ("核心與模式", [
            "/help", "/guide", "/workflows", "/status", "/mode", "/plan", "/execute", "/clear", "/exit",
        ]),
        ("檔案與內容", [
            "/files", "/read", "/find", "/where", "/infra", "/grep", "/search", "/attach", "/fetch",
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
    cmd_to_desc = dict(SLASH_COMMANDS)

    # Stronger visual header for slash help (vision polish)
    header = Panel(
        "[bold]agentX slash commands[/bold]\n"
        "輸入指令即可使用，許多操作會依風險等級要求確認\n\n"
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


def print_tools(tools: ToolRegistry) -> None:
    """Print tools with risk level (GREEN / YELLOW / RED) for better discoverability.
    This moves us closer to the vision in Image 03.
    """
    tool_infos = tools.describe_tools()

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


def print_raw(text: object) -> None:
    console.print(ANSI_RE.sub("", str(text)), markup=False, highlight=False)


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


def print_sessions(settings: Settings) -> None:
    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Start")
    table.add_column("Model")
    table.add_column("Namespace")
    table.add_column("Turns", justify="right")
    table.add_column("Last")
    for path in list_transcripts(settings.workspace):
        overview = transcript_overview(path)
        table.add_row(
            str(overview["name"]),
            str(overview["started"]),
            str(overview["model"]),
            str(overview["namespace"]),
            str(overview["turns"]),
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
    agent: bool = typer.Option(False, "--agent", help="Use agent/tool mode with -p."),
    plan: bool = typer.Option(False, "--plan", help="Start in pure planning mode for -p (only produce high-quality plan + reflection, no tools)."),
    plan_then_execute: bool = typer.Option(False, "--plan-then-execute", help="Plan thoroughly first, then seamlessly continue into execution in the same run (recommended for complex tasks)."),
    orchestrate: bool = typer.Option(False, "--orchestrate", help="Multi-agent orchestration: plan → split → parallel workers."),
    namespace: str | None = typer.Option(None, "--namespace", help="Memory Hall namespace for -p."),
) -> None:
    """Run local Ollama agent workflows."""
    if print_prompt is None:
        return
    if ctx.invoked_subcommand is not None:
        return
    print_raw(run_print_prompt(
        print_prompt,
        namespace=namespace,
        agent_mode=agent,
        plan_mode=plan,
        plan_then_execute=plan_then_execute,
        orchestrate=orchestrate,
    ))
    raise typer.Exit()


def build_runtime(
    settings: Settings,
    *,
    approval_policy: ApprovalPolicy | None = None,
) -> tuple[LLMClient, MemoryHallClient, ToolRegistry]:
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
    backend = os.getenv("AGENTX_BACKEND", "ollama").lower()
    llm_client = get_llm_client(
        backend,
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    if (settings.memory_backend or "memhall").lower() == "amh":
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
        return approval_policy.decide(tool, args, risk, approve_interactive)

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
) -> str:
    settings = Settings()
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"

    # Phase A (MT22): 自動從舊單一任務遷移到多任務清單
    migrate_single_task_if_needed(settings.workspace)

    approval_policy = None
    if project_config.approval:
        mode = normalize_approval_mode(project_config.approval)
        approval_policy = ApprovalPolicy(mode)
    ollama, memory, tools = build_runtime(settings, approval_policy=approval_policy)
    attachment_context, _ = build_attachment_context(prompt, settings.workspace)
    if attachment_context:
        prompt = f"{prompt}\n\n{attachment_context}"

    if orchestrate:
        from agentx.orchestrator import Orchestrator
        orch = Orchestrator(settings=settings, llm=ollama, memory=memory, tools=tools, trace=print_trace)
        result = orch.run(prompt, namespace=namespace)
        return result.summary
    if agent_mode:
        # Use headless-optimized prompt when running via -p --agent
        # B1: 自動注入當前任務清單摘要，讓模型更容易維持長期任務狀態
        current_tasks = load_tasks(settings.workspace)
        task_summary = format_task_list_summary(current_tasks)
        system_prompt = build_headless_agent_system_prompt(settings.persona, task_summary, model=settings.model)

        agent_prompt = prompt
        if plan_mode or plan_then_execute:
            # Headless planning (pure plan or plan-then-execute)
            if plan_then_execute:
                agent_prompt = (
                    "你目前處於 PLAN-THEN-EXECUTE 模式（Headless）。\n"
                    "請先進行**完整、深入、高品質的結構化規劃**，並進行認真 Reflection。\n\n"
                    "當你認為規劃已經足夠好且風險可控時：\n"
                    "1. 先輸出一個結構化的 final answer，清楚描述完整方案（目標、步驟、風險、驗證方式）。\n"
                    "2. 然後**立即開始執行**，使用工具逐步實現規劃。\n\n"
                    "規劃格式建議：\n"
                    "1. 目標（Goal）\n"
                    "2. 執行步驟（編號清楚，每步可驗證）\n"
                    "3. 每個步驟預計工具\n"
                    "4. 風險與注意事項\n"
                    "5. 驗證方式\n\n"
                    "使用者任務："
                ) + prompt
            else:
                # Pure plan mode
                agent_prompt = (
                    "你目前處於純 PLAN MODE（Headless）。\n"
                    "這次你只需要產生高品質規劃，**不要使用任何工具**。\n\n"
                    "請先進行完整規劃與認真 Reflection，然後在 final answer 中輸出結構化方案。\n"
                    "規劃完成後不要繼續執行。\n\n"
                    "使用者任務："
                ) + prompt

        compactor = LLMContextCompactor(ollama) if "gemma" in settings.model.lower() else None
        agent_loop = AgentLoop(
            settings=settings,
            ollama=ollama,
            tools=tools,
            namespace=namespace,
            system_prompt=system_prompt,
            compactor=compactor,
        )
        effective_plan_only = plan_mode or plan_then_execute
        return agent_loop.run(agent_prompt, namespace=namespace, plan_only=effective_plan_only)
    return ollama.chat(
        [
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona, model=settings.model)},
            {"role": "user", "content": prompt},
        ],
        json_mode=False,
    )


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
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
) -> None:
    settings = Settings()
    if max_steps is not None:
        settings = settings.with_updates(max_steps=max_steps)
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"
    approval_policy = None
    if project_config.approval:
        mode = normalize_approval_mode(project_config.approval)
        approval_policy = ApprovalPolicy(mode)
    ollama, memory, tools = build_runtime(settings, approval_policy=approval_policy)
    compactor = LLMContextCompactor(ollama) if "gemma" in settings.model.lower() else None
    agent = AgentLoop(settings=settings, ollama=ollama, tools=tools, trace=print_trace, compactor=compactor, memory=memory)
    print_raw(agent.run(prompt, namespace=namespace))


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
    ollama, memory, tools = build_runtime(settings, approval_policy=approval_policy)

    # MT22 後：只使用新多任務清單（legacy 分支已移除）
    current_tasks = load_tasks(settings.workspace)
    task_summary = format_task_list_summary(current_tasks)

    transcript = Transcript(settings.workspace, model=settings.model, namespace=namespace)
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
            commands=SLASH_COMMANDS,
            status_text=status_line,
            full_screen=ui_mode in {"fullscreen", "full-screen"},
        )
        tui.start()
        console = Console(file=tui.writer, force_terminal=False, color_system=None, width=100)
    elif sys.stdin.isatty():
        prompt_session = PromptSession(
            completer=SlashCommandCompleter(SLASH_COMMANDS),
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
