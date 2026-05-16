from __future__ import annotations

import re
import shlex
import sys
import threading
import os
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agentx.approval import ApprovalMode, ApprovalPolicy
from agentx.attachments import extract_file_paths, format_attachment_context, read_attachments
from agentx.config import Settings
from agentx.doctor import run_doctor
from agentx.git_workflow import build_commit_plan, commit_and_push
from agentx.jobs import PromptJobQueue
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaCancelledError, OllamaClient
from agentx.persona import list_personas, normalize_persona
from agentx.prompting import SlashCommandCompleter
from agentx.project_config import load_project_config, set_project_config
from agentx.project_profile import build_project_profile
from agentx.runtime_prompt import build_chat_system_prompt, build_headless_agent_system_prompt
from agentx.safety import Risk
from agentx.task import TaskState, clear_task, finish_task, load_task, start_task
from agentx.tools import DOCKER_COMPOSE_ACTIONS, ToolRegistry, docker_compose_command
from agentx.transcript import Transcript, find_transcript, list_transcripts, summarize_transcript
from agentx.tui import AgentXTui, format_assistant_header

app = typer.Typer(
    help="agentX local Ollama agent shell.",
    no_args_is_help=True,
    invoke_without_command=True,
)
console = Console()
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

SLASH_COMMANDS = [
    ("/help", "列出所有 slash command 與中文說明"),
    ("/init", "掃描 repo 並寫入 project profile 到 Memory Hall"),
    ("/task [TEXT|status|done|clear]", "設定或查看目前任務狀態"),
    ("/doctor", "檢查 Ollama、模型、Memory Hall、git、uv 狀態"),
    ("/config", "顯示目前 agentX 設定"),
    ("/config set KEY VALUE", "寫入 .agentx/config.toml"),
    ("/tools", "列出 agent 模式可用工具與中文說明"),
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
    ("/search PATTERN", "在 repo 內搜尋文字"),
    ("/fetch URL", "讀取指定外部網頁文字，會阻擋 localhost 與私有網段"),
    ("/git", "顯示 git status"),
    ("/diff [PATH]", "顯示 git diff，可指定單一檔案"),
    ("/apply PATCH_FILE", "套用 workspace 內 patch 檔，會先要求 approval"),
    ("/approval [ask|auto|off]", "查看或切換 YELLOW 工具 approval policy"),
    ("/memory QUERY", "查詢目前 namespace 的 Memory Hall 記憶"),
    ("/run COMMAND", "執行固定 allowlist 命令"),
    ("/docker [ps|build|up|logs|down]", "執行 workspace 內 Docker Compose allowlist 指令"),
    ("/test", "執行固定 allowlist 驗證：ruff check 與 pytest"),
    ("/review", "收集 git diff 與測試結果，輸出 findings-first review"),
    ("/commit [MESSAGE]", "跑測試後逐檔 stage、中文 commit 並 push"),
    ("/plan", "切換 plan 模式；plan 模式只討論方案，不使用工具"),
    ("/execute", "從 plan 模式切換至執行模式，後續將可使用工具實際執行方案"),
    ("/mode chat", "切換到純聊天模式，不使用工具，速度較快"),
    ("/mode agent", "切換到 agent 工具模式，可使用 repo / git / Memory Hall 工具"),
    ("/models", "列出 Ollama 目前可用模型"),
    ("/model [MODEL]", "查看或切換 Ollama 模型，例如 /model gemma4:31b"),
    ("/persona [default|tutor]", "查看或切換人格設定；tutor 是女子大學生家庭教師模式"),
    ("/remember TEXT", "把指定內容寫入目前 Memory Hall namespace"),
    ("/status", "顯示目前模型、模式、namespace、訊息數與粗估 context tokens"),
    ("/clear", "清空目前 shell session 上下文，並重新載入 repo 與 Memory Hall context"),
    ("/exit", "離開 agentX shell"),
    ("/quit", "離開 agentX shell，同 /exit"),
]


def print_trace(message: str) -> None:
    console.print(f"[dim][trace] {escape(message)}[/dim]")


def slash_command_hint() -> str:
    return "Commands: " + " ".join(command for command, _ in SLASH_COMMANDS)


def print_slash_help() -> None:
    table = Table(title="agentX slash commands", show_header=True, header_style="bold")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("中文說明")
    for command, description in SLASH_COMMANDS:
        table.add_row(command, description)
    console.print(table)


def print_tools(tools: ToolRegistry) -> None:
    table = Table(title="agentX tools", show_header=True, header_style="bold")
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("中文說明")
    for name, description in tools.describe_tools().items():
        table.add_row(name, description)
    console.print(table)


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


def print_sessions(settings: Settings) -> None:
    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    for path in list_transcripts(settings.workspace):
        table.add_row(path.stem, str(path))
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
    table.add_row("GREEN", "auto allow")
    table.add_row("YELLOW", "ask / auto / off")
    table.add_row("RED", "always block")
    console.print(table)


def print_task(task: TaskState) -> None:
    table = Table(title="agentX task", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("title", task.title or "(none)")
    table.add_row("status", task.status)
    table.add_row("created_at", task.created_at or "(none)")
    table.add_row("updated_at", task.updated_at or "(none)")
    console.print(table)


def format_plan_status(enabled: bool) -> str:
    """Return user-friendly plan mode status string."""
    return "on（只討論方案，不使用工具）" if enabled else "off"


def build_status_line(model: str, plan_mode: bool, context_pct: int) -> str:
    """Build the bottom status line text shown in TUI and classic prompt mode."""
    plan_marker = " | PLAN" if plan_mode else ""
    return f"{model}{plan_marker} | context {context_pct}%"


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
    task: TaskState,
) -> None:
    table = Table(title="agentX config", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("model", settings.model)
    table.add_row("ollama_url", settings.ollama_url)
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
    table.add_row("task", task.title or "(none)")
    table.add_row("task_status", task.status)
    console.print(table)


def print_doctor(settings: Settings, memory: MemoryHallClient, ollama: OllamaClient) -> None:
    table = Table(title="agentX doctor", show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("OK")
    table.add_column("Detail")
    for name, ok, detail in run_doctor(settings, memory, ollama):
        table.add_row(name, "yes" if ok else "no", detail)
    console.print(table)


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
    result = tools.run("memory_write", {"content": profile, "namespace": namespace})
    if result.ok:
        return "project profile written to Memory Hall\n\n" + profile[:4000]
    return "project profile write failed\n\n" + result.content


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    print_prompt: str | None = typer.Option(None, "-p", "--print", help="Print one response and exit."),
    agent: bool = typer.Option(False, "--agent", help="Use agent/tool mode with -p."),
    plan: bool = typer.Option(False, "--plan", help="Start in planning mode for -p (model will plan thoroughly first; can suggest execution)."),
    namespace: str | None = typer.Option(None, "--namespace", help="Memory Hall namespace for -p."),
) -> None:
    """Run local Ollama agent workflows."""
    if print_prompt is None:
        return
    if ctx.invoked_subcommand is not None:
        return
    print_raw(run_print_prompt(print_prompt, namespace=namespace, agent_mode=agent, plan_mode=plan))
    raise typer.Exit()


def build_runtime(
    settings: Settings,
    *,
    approval_policy: ApprovalPolicy | None = None,
) -> tuple[OllamaClient, MemoryHallClient, ToolRegistry]:
    ollama = OllamaClient(
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    memory = MemoryHallClient(
        base_url=settings.memory_hall_url,
        token=settings.memory_hall_token,
    )
    def approve(tool: str, args: dict[str, object], risk: Risk) -> bool:
        if approval_policy is None:
            return False
        return approval_policy.decide(tool, args, risk, approve_interactive)

    tools = ToolRegistry(
        workspace=settings.workspace,
        memory=memory,
        approver=approve if approval_policy is not None else None,
    )
    return ollama, memory, tools


def run_print_prompt(prompt: str, namespace: str | None, agent_mode: bool = False, plan_mode: bool = False) -> str:
    settings = Settings()
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"
    ollama, _, tools = build_runtime(settings)
    attachment_context, _ = build_attachment_context(prompt, settings.workspace)
    if attachment_context:
        prompt = f"{prompt}\n\n{attachment_context}"
    if agent_mode:
        # Use headless-optimized prompt when running via -p --agent
        system_prompt = build_headless_agent_system_prompt(settings.persona)

        agent_prompt = prompt
        if plan_mode:
            # Stronger planning instruction for headless plan mode
            agent_prompt = (
                "你目前處於 PLAN MODE（Headless 模式）。\n"
                "請先進行深入且結構化的規劃，絕對不要急著呼叫工具。\n\n"
                "請嚴格按照以下格式輸出規劃：\n"
                "1. 目標（Goal）\n"
                "2. 執行步驟（用編號清楚列出，每一步都要可驗證）\n"
                "3. 每個步驟預計使用的工具或指令\n"
                "4. 可能的風險、依賴或注意事項\n"
                "5. 如何驗證成功\n\n"
                "規劃完成後，請先進行 Reflection，檢討規劃的完整性與可行性。\n"
                "Reflection 結束後，你可以選擇：\n"
                "- 繼續優化規劃\n"
                "- 在 final answer 中清楚描述完整方案，並建議是否可以進入執行階段\n\n"
                "使用者任務："
            ) + prompt

        agent_loop = AgentLoop(
            settings=settings,
            ollama=ollama,
            tools=tools,
            namespace=namespace,
            system_prompt=system_prompt,
        )
        return agent_loop.run(agent_prompt, namespace=namespace, plan_only=plan_mode)
    return ollama.chat(
        [
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona)},
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
    task: TaskState,
    note: str | None = None,
) -> str:
    recent = "\n".join(f"- [{item_mode}] {prompt}" for item_mode, prompt in history[-10:])
    note_section = f"\n人類補充：{note}\n" if note else ""
    return (
        f"agentX session handoff\n"
        f"時間：{datetime.now().isoformat(timespec='seconds')}\n"
        f"workspace：{settings.workspace}\n"
        f"model：{settings.model}\n"
        f"mode：{mode}\n"
        f"namespace：{namespace}\n"
        f"task：{task.title or '(none)'} [{task.status}]\n"
        f"transcript：{transcript.path}\n"
        f"{note_section}"
        f"最近互動：\n{recent if recent else '- 無使用者任務'}"
    )


def write_handoff(
    tools: ToolRegistry,
    *,
    settings: Settings,
    namespace: str,
    mode: str,
    history: list[tuple[str, str]],
    transcript: Transcript,
    task: TaskState,
    note: str | None = None,
) -> str:
    content = build_handoff(
        settings=settings,
        namespace=namespace,
        mode=mode,
        history=history,
        transcript=transcript,
        task=task,
        note=note,
    )
    result = tools.run("memory_write", {"content": content, "namespace": namespace})
    if result.ok:
        return f"handoff written to {namespace}"
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
    ollama, _, tools = build_runtime(settings)
    agent = AgentLoop(settings=settings, ollama=ollama, tools=tools, trace=print_trace)
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
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona)},
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
    approval_policy = ApprovalPolicy(
        mode=ApprovalMode(project_config.approval) if project_config.approval else ApprovalMode.ASK
    )
    ollama, memory, tools = build_runtime(settings, approval_policy=approval_policy)
    task = load_task(settings.workspace)
    transcript = Transcript(settings.workspace, model=settings.model, namespace=namespace)
    transcript.write("task", {"title": task.title, "status": task.status})
    agent_session = AgentSession(
        settings=settings,
        ollama=ollama,
        tools=tools,
        namespace=namespace,
        trace=print_trace,
    )
    chat_messages = [
        {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona)}
    ]
    history: list[tuple[str, str]] = []
    plan_mode = False
    job_queue = PromptJobQueue()
    prompt_active = threading.Event()
    current_cancel = threading.Event()
    prompt_session: PromptSession[str] | None = None
    tui: AgentXTui | None = None
    original_console = console

    def status_line() -> str:
        pct = context_percent(settings, agent_session, chat_messages)
        return build_status_line(settings.model, plan_mode, pct)

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
                if mode == "agent":
                    history.append((mode, queued_prompt))
                    transcript.write("user", {"mode": mode, "content": queued_prompt})
                    agent_prompt = queued_prompt
                    if plan_mode:
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

                history.append((mode, queued_prompt))
                transcript.write("user", {"mode": mode, "content": queued_prompt})
                chat_prompt = queued_prompt
                if plan_mode:
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
            (
                f"model={settings.model} mode={mode} namespace={namespace}\n"
                + escape(slash_command_hint())
            ),
            title="agentX shell",
        )
    )

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
            except (EOFError, KeyboardInterrupt):
                wait_for_prompt_worker()
                if history and settings.auto_handoff:
                    message = write_handoff(
                        tools,
                        settings=settings,
                        namespace=namespace,
                        mode=mode,
                        history=history,
                        transcript=transcript,
                        task=task,
                    )
                    transcript.write("handoff", {"auto": True, "result": message})
                    print_raw(f"\n{message}")
                console.print("\nbye")
                break

            if not prompt:
                continue
            if prompt_session is not None:
                print_block(f"agentX: {prompt}")
            if prompt in {"/exit", "/quit"}:
                wait_for_prompt_worker()
                if history and settings.auto_handoff:
                    message = write_handoff(
                        tools,
                        settings=settings,
                        namespace=namespace,
                        mode=mode,
                        history=history,
                        transcript=transcript,
                        task=task,
                    )
                    transcript.write("handoff", {"auto": True, "result": message})
                    print_raw(message)
                transcript.write("session_end", {"reason": prompt})
                break
            if prompt.startswith("/") and not prompt.startswith(("/jobs", "/cancel")):
                wait_for_prompt_worker()
            if prompt == "/help":
                transcript.write("slash_command", {"command": prompt})
                print_slash_help()
                continue
            if prompt == "/config":
                transcript.write("slash_command", {"command": prompt})
                print_config(settings, namespace, mode, approval_policy, task)
                continue
            if prompt.startswith("/config set "):
                parts = prompt.split(maxsplit=3)
                if len(parts) != 4:
                    console.print("usage: /config set KEY VALUE")
                    continue
                _, _, key, value = parts
                try:
                    updated = set_project_config(settings.workspace, key, value)
                except ValueError as exc:
                    console.print(str(exc))
                    continue
                transcript.write("slash_command", {"command": prompt, "config": key})
                console.print(f"config updated: {key}")
                print_raw(updated)
                continue
            if prompt == "/task":
                transcript.write("slash_command", {"command": prompt})
                task = load_task(settings.workspace)
                print_task(task)
                continue
            if prompt.startswith("/task "):
                value = prompt.removeprefix("/task ").strip()
                if value == "status":
                    task = load_task(settings.workspace)
                elif value == "done":
                    task = finish_task(settings.workspace)
                elif value == "clear":
                    task = clear_task(settings.workspace)
                else:
                    task = start_task(settings.workspace, value)
                transcript.write("task", {"title": task.title, "status": task.status})
                print_task(task)
                continue
            if prompt == "/doctor":
                transcript.write("slash_command", {"command": prompt})
                print_doctor(settings, memory, ollama)
                continue
            if prompt == "/init":
                transcript.write("slash_command", {"command": prompt})
                output = run_init(settings, tools, namespace)
                transcript.write("init", {"content": output[:4000]})
                print_raw(output)
                continue
            if prompt == "/tools":
                transcript.write("slash_command", {"command": prompt})
                print_tools(tools)
                continue
            if prompt == "/context":
                transcript.write("slash_command", {"command": prompt})
                print_context(agent_session, chat_messages)
                continue
            if prompt == "/compact":
                transcript.write("slash_command", {"command": prompt})
                result = agent_session.compact()
                transcript.write("compact", {"result": result})
                print_raw(result)
                continue
            if prompt == "/history":
                transcript.write("slash_command", {"command": prompt})
                print_history(history)
                continue
            if prompt == "/jobs":
                transcript.write("slash_command", {"command": prompt})
                print_jobs(job_queue)
                continue
            if prompt.startswith("/cancel"):
                value = prompt.removeprefix("/cancel").strip() or None
                transcript.write("slash_command", {"command": prompt})
                print_raw(cancel_jobs(job_queue, value, current_cancel))
                continue
            if prompt == "/sessions":
                transcript.write("slash_command", {"command": prompt})
                print_sessions(settings)
                continue
            if prompt == "/transcript":
                transcript.write("slash_command", {"command": prompt})
                console.print(str(transcript.path))
                continue
            if prompt.startswith("/handoff"):
                note = prompt.removeprefix("/handoff").strip() or None
                message = write_handoff(
                    tools,
                    settings=settings,
                    namespace=namespace,
                    mode=mode,
                    history=history,
                    transcript=transcript,
                    task=task,
                    note=note,
                )
                transcript.write("handoff", {"auto": False, "note": note, "result": message})
                print_raw(message)
                continue
            if prompt.startswith("/resume"):
                name = prompt.removeprefix("/resume").strip() or "latest"
                resume_path = find_transcript(settings.workspace, name)
                if resume_path is None:
                    console.print(f"transcript not found: {name}")
                    continue
                summary = summarize_transcript(resume_path)
                agent_session.messages.append({"role": "system", "content": summary})
                chat_messages.append({"role": "system", "content": summary})
                transcript.write("resume", {"source": str(resume_path), "summary": summary[:2000]})
                console.print(f"resumed {resume_path}")
                continue
            if prompt.startswith("/files"):
                path = prompt.removeprefix("/files").strip() or "."
                result = tools.run("list_files", {"path": path})
                transcript.write(
                    "tool",
                    {"command": "/files", "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
                continue
            if prompt.startswith("/read "):
                path = prompt.removeprefix("/read ").strip()
                result = tools.run("read_file", {"path": path})
                transcript.write(
                    "tool",
                    {"command": "/read", "path": path, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
                continue
            if prompt.startswith("/attach "):
                attachment_text = prompt.removeprefix("/attach ").strip()
                attachment_context, attachment_paths = build_attachment_context(
                    attachment_text,
                    settings.workspace,
                )
                if not attachment_context:
                    print_raw("no readable attachment found")
                    continue
                agent_session.messages.append({"role": "system", "content": attachment_context})
                chat_messages.append({"role": "system", "content": attachment_context})
                transcript.write("attachments", {"paths": attachment_paths})
                print_raw("attached files:\n" + "\n".join(attachment_paths))
                continue
            if prompt.startswith("/search "):
                pattern = prompt.removeprefix("/search ").strip()
                result = tools.run("search_text", {"pattern": pattern})
                transcript.write(
                    "tool",
                    {"command": "/search", "pattern": pattern, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
                continue
            if prompt.startswith("/fetch "):
                url = prompt.removeprefix("/fetch ").strip()
                result = tools.run("web_fetch", {"url": url})
                transcript.write(
                    "tool",
                    {"command": "/fetch", "url": url, "ok": result.ok, "content": result.content[:4000]},
                )
                print_tool_result(result.content if result.ok else f"fetch failed: {result.content}")
                continue
            if prompt == "/git":
                result = tools.run("git_status", {})
                transcript.write("tool", {"command": "/git", "ok": result.ok, "content": result.content[:2000]})
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
                continue
            if prompt.startswith("/diff"):
                path = prompt.removeprefix("/diff").strip()
                args = {"path": path} if path else {}
                result = tools.run("git_diff", args)
                transcript.write(
                    "tool",
                    {"command": "/diff", "path": path, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
                continue
            if prompt.startswith("/apply "):
                path = prompt.removeprefix("/apply ").strip()
                patch_path = (settings.workspace / path).resolve()
                if settings.workspace != patch_path and settings.workspace not in patch_path.parents:
                    console.print("patch path escapes workspace")
                    continue
                if not patch_path.is_file():
                    console.print(f"patch file not found: {path}")
                    continue
                patch = patch_path.read_text(encoding="utf-8", errors="replace")
                result = tools.run("apply_patch", {"patch": patch})
                transcript.write(
                    "tool",
                    {"command": "/apply", "path": path, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"patch failed: {result.content}")
                continue
            if prompt == "/approval":
                transcript.write("slash_command", {"command": prompt})
                print_approval(approval_policy)
                continue
            if prompt.startswith("/approval "):
                mode_value = prompt.removeprefix("/approval ").strip()
                try:
                    approval_policy.mode = ApprovalMode(mode_value)
                except ValueError:
                    console.print("usage: /approval ask|auto|off")
                    continue
                transcript.write("slash_command", {"command": prompt, "approval": approval_policy.mode.value})
                print_approval(approval_policy)
                continue
            if prompt.startswith("/memory "):
                query = prompt.removeprefix("/memory ").strip()
                result = tools.run("memory_search", {"query": query, "namespace": namespace})
                transcript.write(
                    "tool",
                    {"command": "/memory", "query": query, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"memory search failed: {result.content}")
                continue
            if prompt.startswith("/run "):
                command = prompt.removeprefix("/run ").strip()
                result = tools.run("run_command", {"command": command})
                transcript.write(
                    "tool",
                    {"command": "/run", "input": command, "ok": result.ok, "content": result.content[:4000]},
                )
                print_tool_result(result.content if result.ok else f"run failed: {result.content}")
                continue
            if prompt.startswith("/docker"):
                docker_args = parse_docker_prompt(prompt)
                if docker_args is None:
                    console.print("usage: /docker ps|build|up|logs [SERVICE]|down")
                    continue
                action = str(docker_args.pop("action"))
                try:
                    command = docker_compose_command(
                        settings.workspace,
                        action,
                        service=str(docker_args["service"]) if "service" in docker_args else None,
                    )
                except Exception as exc:
                    print_raw(f"docker command rejected: {type(exc).__name__}: {exc}")
                    continue
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
                continue
            if prompt == "/test":
                result = tools.run("run_tests", {})
                transcript.write("tool", {"command": "/test", "ok": result.ok, "content": result.content[:4000]})
                print_tool_result(result.content if result.ok else f"驗證失敗：{result.content}")
                continue
            if prompt == "/review":
                transcript.write("slash_command", {"command": prompt})
                output = run_review(ollama, tools)
                transcript.write("review", {"content": output[:4000]})
                print_raw(output)
                continue
            if prompt.startswith("/commit"):
                message = prompt.removeprefix("/commit").strip() or None
                transcript.write("slash_command", {"command": prompt})
                output = run_commit_flow(settings, tools, message)
                transcript.write("commit", {"message": message, "content": output[:4000]})
                print_raw(output)
                continue
            if prompt == "/plan":
                plan_mode = not plan_mode
                agent_session.plan_only = plan_mode
                transcript.write("slash_command", {"command": prompt, "plan": plan_mode})
                status = format_plan_status(plan_mode)
                console.print(f"plan mode: {status}")
                continue
            if prompt == "/execute":
                if not plan_mode and not agent_session.plan_only:
                    console.print("目前不在 plan 模式中")
                    continue
                plan_mode = False
                agent_session.plan_only = False
                transcript.write("slash_command", {"command": prompt, "plan": False, "action": "execute"})

                # 注入一則 system message，告知模型規劃階段結束，可以開始執行
                execute_message = (
                    "規劃階段已結束，使用者已同意上述方案。\n"
                    "你現在已切換至執行模式。請使用工具實際執行方案中的每個步驟。\n"
                    "如果需要，可以先列出下一步要做的動作，再逐步呼叫工具完成。"
                )
                agent_session.messages.append({"role": "system", "content": execute_message})
                chat_messages.append({"role": "system", "content": execute_message})

                console.print("已切換至執行模式。後續提示將可使用工具實際執行方案。")
                continue
            if prompt.startswith("/remember "):
                content = prompt.removeprefix("/remember ").strip()
                if not content:
                    console.print("usage: /remember 要寫入 Memory Hall 的內容")
                    continue
                result = tools.run("memory_write", {"content": content, "namespace": namespace})
                transcript.write("tool", {"command": "/remember", "ok": result.ok, "content": content})
                if result.ok:
                    console.print(f"remembered in {namespace}")
                else:
                    console.print(f"remember failed: {result.content}")
                continue
            if prompt.startswith("/mode "):
                next_mode = prompt.removeprefix("/mode ").strip()
                if next_mode not in {"chat", "agent"}:
                    console.print("mode must be chat or agent")
                    continue
                mode = next_mode
                transcript.write("slash_command", {"command": prompt, "mode": mode})
                console.print(f"mode={mode}")
                continue
            if prompt == "/models":
                transcript.write("slash_command", {"command": prompt})
                try:
                    models = ollama.list_models()
                except Exception as exc:
                    console.print(f"models failed: {type(exc).__name__}: {exc}")
                    continue
                print_tool_result("\n".join(models))
                continue
            if prompt == "/model":
                transcript.write("slash_command", {"command": prompt, "model": settings.model})
                console.print(f"model={settings.model}")
                console.print("usage: /model MODEL")
                console.print("example: /model gemma4:31b")
                console.print("list models: /models")
                continue
            if prompt.startswith("/model "):
                model = prompt.removeprefix("/model ").strip()
                if not model:
                    console.print("usage: /model gemma4:e2b")
                    continue
                settings = settings.with_updates(model=model)
                ollama = OllamaClient(
                    base_url=settings.ollama_url,
                    model=settings.model,
                    timeout=settings.ollama_timeout,
                )
                agent_session.ollama = ollama
                transcript.write("slash_command", {"command": prompt, "model": settings.model})
                console.print(f"model={settings.model}")
                continue
            if prompt == "/persona":
                transcript.write("slash_command", {"command": prompt, "persona": settings.persona})
                console.print(f"persona={settings.persona}")
                print_raw(list_personas())
                continue
            if prompt.startswith("/persona "):
                value = prompt.removeprefix("/persona ").strip()
                try:
                    persona = normalize_persona(value)
                except ValueError as exc:
                    console.print(str(exc))
                    continue
                settings = settings.with_updates(persona=persona)
                agent_session.settings = settings
                agent_session.clear()
                chat_messages = [
                    {
                        "role": "system",
                        "content": build_chat_system_prompt(settings.workspace, settings.persona),
                    }
                ]
                transcript.write("slash_command", {"command": prompt, "persona": settings.persona})
                console.print(f"persona={settings.persona}")
                continue
            if prompt == "/status":
                transcript.write("slash_command", {"command": prompt})
                approx_tokens = agent_session.context_chars // 4
                plan_status = format_plan_status(plan_mode)
                console.print(
                    f"model={settings.model} mode={mode} namespace={namespace} "
                    f"persona={settings.persona} plan={plan_status} "
                    f"agent_messages={agent_session.message_count} "
                    f"agent_context~{approx_tokens} tokens chat_messages={len(chat_messages)}"
                )
                continue
            if prompt == "/clear":
                agent_session.clear()
                chat_messages = [
                    {
                        "role": "system",
                        "content": build_chat_system_prompt(settings.workspace, settings.persona),
                    }
                ]
                transcript.write("slash_command", {"command": prompt})
                console.print("cleared")
                continue

            # Natural language trigger for execute when in plan mode
            if (plan_mode or agent_session.plan_only) and is_natural_execute_trigger(prompt):
                plan_mode = False
                agent_session.plan_only = False
                transcript.write("slash_command", {"command": "natural_execute", "original": prompt})

                execute_message = (
                    "使用者已透過自然語言要求開始執行。\n"
                    "規劃階段結束，現在切換至執行模式。請使用工具逐步完成方案。"
                )
                agent_session.messages.append({"role": "system", "content": execute_message})
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
