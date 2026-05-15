from __future__ import annotations

import os
import re
import shlex
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
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
from agentx.runtime_prompt import build_chat_system_prompt
from agentx.safety import Risk
from agentx.task import TaskState, clear_task, finish_task, load_task, start_task
from agentx.tools import DOCKER_COMPOSE_ACTIONS, ToolRegistry, builtin_tools, docker_compose_command
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

NON_BLOCKING_COMMANDS = {"/jobs", "/cancel"}


@dataclass
class ShellState:
    settings: Settings
    ollama: OllamaClient
    memory: MemoryHallClient
    tools: ToolRegistry
    agent_session: AgentSession
    transcript: Transcript
    job_queue: PromptJobQueue
    approval_policy: ApprovalPolicy
    task: TaskState
    namespace: str
    mode: str
    plan_mode: bool = False
    chat_messages: list[dict[str, str]] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)
    current_cancel: threading.Event = field(default_factory=threading.Event)
    prompt_active: threading.Event = field(default_factory=threading.Event)
    tui: AgentXTui | None = None
    should_exit: bool = False
    exit_reason: str | None = None


SlashHandler = Callable[[ShellState, str], None]


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


def _print_tool_run(state: ShellState, tool: str, args: dict[str, object], slash: str, failure_prefix: str = "工具執行失敗", transcript_extra: dict[str, object] | None = None) -> None:
    result = state.tools.run(tool, args)
    record: dict[str, object] = {
        "command": slash,
        "ok": result.ok,
        "content": result.content[:2000],
    }
    if transcript_extra:
        record.update(transcript_extra)
    state.transcript.write("tool", record)
    print_tool_result(result.content if result.ok else f"{failure_prefix}：{result.content}")


def cmd_help(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/help"})
    print_slash_help()


def cmd_config(state: ShellState, arg: str) -> None:
    if arg.startswith("set "):
        parts = arg.split(maxsplit=2)
        if len(parts) != 3:
            console.print("usage: /config set KEY VALUE")
            return
        _, key, value = parts
        try:
            updated = set_project_config(state.settings.workspace, key, value)
        except ValueError as exc:
            console.print(str(exc))
            return
        state.transcript.write("slash_command", {"command": f"/config set {key}", "config": key})
        console.print(f"config updated: {key}")
        print_raw(updated)
        return
    if arg:
        console.print("usage: /config | /config set KEY VALUE")
        return
    state.transcript.write("slash_command", {"command": "/config"})
    print_config(state.settings, state.namespace, state.mode, state.approval_policy, state.task)


def cmd_task(state: ShellState, arg: str) -> None:
    value = arg.strip()
    if not value:
        state.transcript.write("slash_command", {"command": "/task"})
        state.task = load_task(state.settings.workspace)
    else:
        if value == "status":
            state.task = load_task(state.settings.workspace)
        elif value == "done":
            state.task = finish_task(state.settings.workspace)
        elif value == "clear":
            state.task = clear_task(state.settings.workspace)
        else:
            state.task = start_task(state.settings.workspace, value)
        state.transcript.write("task", {"title": state.task.title, "status": state.task.status})
    print_task(state.task)


def cmd_doctor(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/doctor"})
    print_doctor(state.settings, state.memory, state.ollama)


def cmd_init(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/init"})
    output = run_init(state.settings, state.tools, state.namespace)
    state.transcript.write("init", {"content": output[:4000]})
    print_raw(output)


def cmd_tools(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/tools"})
    print_tools(state.tools)


def cmd_context(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/context"})
    print_context(state.agent_session, state.chat_messages)


def cmd_compact(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/compact"})
    result = state.agent_session.compact()
    state.transcript.write("compact", {"result": result})
    print_raw(result)


def cmd_history(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/history"})
    print_history(state.history)


def cmd_jobs(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/jobs"})
    print_jobs(state.job_queue)


def cmd_cancel(state: ShellState, arg: str) -> None:
    value = arg.strip() or None
    state.transcript.write("slash_command", {"command": "/cancel"})
    print_raw(cancel_jobs(state.job_queue, value, state.current_cancel))


def cmd_sessions(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/sessions"})
    print_sessions(state.settings)


def cmd_transcript(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/transcript"})
    console.print(str(state.transcript.path))


def cmd_handoff(state: ShellState, arg: str) -> None:
    note = arg.strip() or None
    message = write_handoff(
        state.tools,
        settings=state.settings,
        namespace=state.namespace,
        mode=state.mode,
        history=state.history,
        transcript=state.transcript,
        task=state.task,
        note=note,
    )
    state.transcript.write("handoff", {"auto": False, "note": note, "result": message})
    print_raw(message)


def cmd_resume(state: ShellState, arg: str) -> None:
    name = arg.strip() or "latest"
    resume_path = find_transcript(state.settings.workspace, name)
    if resume_path is None:
        console.print(f"transcript not found: {name}")
        return
    summary = summarize_transcript(resume_path)
    state.agent_session.messages.append({"role": "system", "content": summary})
    state.chat_messages.append({"role": "system", "content": summary})
    state.transcript.write("resume", {"source": str(resume_path), "summary": summary[:2000]})
    console.print(f"resumed {resume_path}")


def cmd_files(state: ShellState, arg: str) -> None:
    path = arg.strip() or "."
    _print_tool_run(state, "list_files", {"path": path}, "/files")


def cmd_read(state: ShellState, arg: str) -> None:
    path = arg.strip()
    if not path:
        console.print("usage: /read PATH")
        return
    _print_tool_run(state, "read_file", {"path": path}, "/read", transcript_extra={"path": path})


def cmd_attach(state: ShellState, arg: str) -> None:
    attachment_text = arg.strip()
    if not attachment_text:
        console.print("usage: /attach PATH [PATH...]")
        return
    attachment_context, attachment_paths = build_attachment_context(
        attachment_text,
        state.settings.workspace,
    )
    if not attachment_context:
        print_raw("no readable attachment found")
        return
    state.agent_session.messages.append({"role": "system", "content": attachment_context})
    state.chat_messages.append({"role": "system", "content": attachment_context})
    state.transcript.write("attachments", {"paths": attachment_paths})
    print_raw("attached files:\n" + "\n".join(attachment_paths))


def cmd_search(state: ShellState, arg: str) -> None:
    pattern = arg.strip()
    if not pattern:
        console.print("usage: /search PATTERN")
        return
    _print_tool_run(state, "search_text", {"pattern": pattern}, "/search", transcript_extra={"pattern": pattern})


def cmd_git(state: ShellState, arg: str) -> None:
    _print_tool_run(state, "git_status", {}, "/git")


def cmd_diff(state: ShellState, arg: str) -> None:
    path = arg.strip()
    args = {"path": path} if path else {}
    _print_tool_run(state, "git_diff", args, "/diff", transcript_extra={"path": path})


def cmd_apply(state: ShellState, arg: str) -> None:
    path = arg.strip()
    if not path:
        console.print("usage: /apply PATCH_FILE")
        return
    patch_path = (state.settings.workspace / path).resolve()
    if state.settings.workspace != patch_path and state.settings.workspace not in patch_path.parents:
        console.print("patch path escapes workspace")
        return
    if not patch_path.is_file():
        console.print(f"patch file not found: {path}")
        return
    patch = patch_path.read_text(encoding="utf-8", errors="replace")
    _print_tool_run(
        state,
        "apply_patch",
        {"patch": patch},
        "/apply",
        failure_prefix="patch failed",
        transcript_extra={"path": path},
    )


def cmd_approval(state: ShellState, arg: str) -> None:
    value = arg.strip()
    if not value:
        state.transcript.write("slash_command", {"command": "/approval"})
        print_approval(state.approval_policy)
        return
    try:
        state.approval_policy.mode = ApprovalMode(value)
    except ValueError:
        console.print("usage: /approval ask|auto|off")
        return
    state.transcript.write(
        "slash_command",
        {"command": f"/approval {value}", "approval": state.approval_policy.mode.value},
    )
    print_approval(state.approval_policy)


def cmd_memory(state: ShellState, arg: str) -> None:
    query = arg.strip()
    if not query:
        console.print("usage: /memory QUERY")
        return
    _print_tool_run(
        state,
        "memory_search",
        {"query": query, "namespace": state.namespace},
        "/memory",
        failure_prefix="memory search failed",
        transcript_extra={"query": query},
    )


def cmd_run(state: ShellState, arg: str) -> None:
    command = arg.strip()
    if not command:
        console.print("usage: /run COMMAND")
        return
    _print_tool_run(
        state,
        "run_command",
        {"command": command},
        "/run",
        failure_prefix="run failed",
        transcript_extra={"input": command},
    )


def cmd_docker(state: ShellState, arg: str) -> None:
    prompt_text = f"/docker {arg}".strip()
    docker_args = parse_docker_prompt(prompt_text)
    if docker_args is None:
        console.print("usage: /docker ps|build|up|logs [SERVICE]|down")
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
    result = state.tools.run(f"docker_compose_{action}", docker_args)
    state.transcript.write(
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


def cmd_test(state: ShellState, arg: str) -> None:
    result = state.tools.run("run_tests", {})
    state.transcript.write("tool", {"command": "/test", "ok": result.ok, "content": result.content[:4000]})
    print_tool_result(result.content if result.ok else f"驗證失敗：{result.content}")


def cmd_review(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/review"})
    output = run_review(state.ollama, state.tools)
    state.transcript.write("review", {"content": output[:4000]})
    print_raw(output)


def cmd_commit(state: ShellState, arg: str) -> None:
    message = arg.strip() or None
    state.transcript.write("slash_command", {"command": "/commit"})
    output = run_commit_flow(state.settings, state.tools, message)
    state.transcript.write("commit", {"message": message, "content": output[:4000]})
    print_raw(output)


def cmd_plan(state: ShellState, arg: str) -> None:
    state.plan_mode = not state.plan_mode
    state.transcript.write("slash_command", {"command": "/plan", "plan": state.plan_mode})
    console.print(f"plan={'on' if state.plan_mode else 'off'}")


def cmd_remember(state: ShellState, arg: str) -> None:
    content = arg.strip()
    if not content:
        console.print("usage: /remember 要寫入 Memory Hall 的內容")
        return
    result = state.tools.run("memory_write", {"content": content, "namespace": state.namespace})
    state.transcript.write("tool", {"command": "/remember", "ok": result.ok, "content": content})
    if result.ok:
        console.print(f"remembered in {state.namespace}")
    else:
        console.print(f"remember failed: {result.content}")


def cmd_mode(state: ShellState, arg: str) -> None:
    next_mode = arg.strip()
    if next_mode not in {"chat", "agent"}:
        console.print("mode must be chat or agent")
        return
    state.mode = next_mode
    state.transcript.write("slash_command", {"command": f"/mode {next_mode}", "mode": next_mode})
    console.print(f"mode={next_mode}")


def cmd_models(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/models"})
    try:
        models = state.ollama.list_models()
    except Exception as exc:
        console.print(f"models failed: {type(exc).__name__}: {exc}")
        return
    print_tool_result("\n".join(models))


def cmd_model(state: ShellState, arg: str) -> None:
    model = arg.strip()
    if not model:
        state.transcript.write("slash_command", {"command": "/model", "model": state.settings.model})
        console.print(f"model={state.settings.model}")
        console.print("usage: /model MODEL")
        console.print("example: /model gemma4:31b")
        console.print("list models: /models")
        return
    state.settings = state.settings.with_updates(model=model)
    old_ollama = state.ollama
    state.ollama = OllamaClient(
        base_url=state.settings.ollama_url,
        model=state.settings.model,
        timeout=state.settings.ollama_timeout,
    )
    state.agent_session.ollama = state.ollama
    if hasattr(old_ollama, "close"):
        old_ollama.close()
    state.transcript.write("slash_command", {"command": f"/model {model}", "model": state.settings.model})
    console.print(f"model={state.settings.model}")


def cmd_persona(state: ShellState, arg: str) -> None:
    value = arg.strip()
    if not value:
        state.transcript.write("slash_command", {"command": "/persona", "persona": state.settings.persona})
        console.print(f"persona={state.settings.persona}")
        print_raw(list_personas())
        return
    try:
        persona = normalize_persona(value)
    except ValueError as exc:
        console.print(str(exc))
        return
    state.settings = state.settings.with_updates(persona=persona)
    state.agent_session.settings = state.settings
    state.agent_session.clear()
    state.chat_messages = [
        {
            "role": "system",
            "content": build_chat_system_prompt(state.settings.workspace, state.settings.persona),
        }
    ]
    state.transcript.write("slash_command", {"command": f"/persona {value}", "persona": state.settings.persona})
    console.print(f"persona={state.settings.persona}")


def cmd_status(state: ShellState, arg: str) -> None:
    state.transcript.write("slash_command", {"command": "/status"})
    approx_tokens = state.agent_session.context_chars // 4
    console.print(
        f"model={state.settings.model} mode={state.mode} namespace={state.namespace} "
        f"persona={state.settings.persona} agent_messages={state.agent_session.message_count} "
        f"agent_context~{approx_tokens} tokens chat_messages={len(state.chat_messages)}"
    )


def cmd_clear(state: ShellState, arg: str) -> None:
    state.agent_session.clear()
    state.chat_messages = [
        {
            "role": "system",
            "content": build_chat_system_prompt(state.settings.workspace, state.settings.persona),
        }
    ]
    state.transcript.write("slash_command", {"command": "/clear"})
    console.print("cleared")


def cmd_exit(state: ShellState, arg: str) -> None:
    state.should_exit = True
    state.exit_reason = "/exit"


def cmd_quit(state: ShellState, arg: str) -> None:
    state.should_exit = True
    state.exit_reason = "/quit"


SLASH_HANDLERS: dict[str, SlashHandler] = {
    "/help": cmd_help,
    "/config": cmd_config,
    "/task": cmd_task,
    "/doctor": cmd_doctor,
    "/init": cmd_init,
    "/tools": cmd_tools,
    "/context": cmd_context,
    "/compact": cmd_compact,
    "/history": cmd_history,
    "/jobs": cmd_jobs,
    "/cancel": cmd_cancel,
    "/sessions": cmd_sessions,
    "/transcript": cmd_transcript,
    "/handoff": cmd_handoff,
    "/resume": cmd_resume,
    "/files": cmd_files,
    "/read": cmd_read,
    "/attach": cmd_attach,
    "/search": cmd_search,
    "/git": cmd_git,
    "/diff": cmd_diff,
    "/apply": cmd_apply,
    "/approval": cmd_approval,
    "/memory": cmd_memory,
    "/run": cmd_run,
    "/docker": cmd_docker,
    "/test": cmd_test,
    "/review": cmd_review,
    "/commit": cmd_commit,
    "/plan": cmd_plan,
    "/remember": cmd_remember,
    "/mode": cmd_mode,
    "/models": cmd_models,
    "/model": cmd_model,
    "/persona": cmd_persona,
    "/status": cmd_status,
    "/clear": cmd_clear,
    "/exit": cmd_exit,
    "/quit": cmd_quit,
}


def dispatch_slash(state: ShellState, prompt: str) -> bool:
    head, _, arg = prompt.partition(" ")
    handler = SLASH_HANDLERS.get(head)
    if handler is None:
        return False
    handler(state, arg)
    return True


def finalize_session(state: ShellState, reason: str | None) -> None:
    if state.history and state.settings.auto_handoff:
        message = write_handoff(
            state.tools,
            settings=state.settings,
            namespace=state.namespace,
            mode=state.mode,
            history=state.history,
            transcript=state.transcript,
            task=state.task,
        )
        state.transcript.write("handoff", {"auto": True, "result": message})
        print_raw(message if reason is None else f"\n{message}")
    if reason is not None:
        state.transcript.write("session_end", {"reason": reason})


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    print_prompt: str | None = typer.Option(None, "-p", "--print", help="Print one response and exit."),
    agent: bool = typer.Option(False, "--agent", help="Use agent/tool mode with -p."),
    namespace: str | None = typer.Option(None, "--namespace", help="Memory Hall namespace for -p."),
) -> None:
    """Run local Ollama agent workflows."""
    if print_prompt is None:
        return
    if ctx.invoked_subcommand is not None:
        return
    print_raw(run_print_prompt(print_prompt, namespace=namespace, agent_mode=agent))
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
        builtin_tools(settings.workspace, memory),
        approver=approve if approval_policy is not None else None,
    )
    return ollama, memory, tools


def run_print_prompt(prompt: str, namespace: str | None, agent_mode: bool = False) -> str:
    settings = Settings()
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"
    ollama, memory, tools = build_runtime(settings)
    attachment_context, _ = build_attachment_context(prompt, settings.workspace)
    if attachment_context:
        prompt = f"{prompt}\n\n{attachment_context}"
    if agent_mode:
        agent_loop = AgentLoop(
            settings=settings,
            ollama=ollama,
            tools=tools,
            memory=memory,
            namespace=namespace,
        )
        return agent_loop.run(prompt, namespace=namespace)
    return ollama.chat(
        [
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona)},
            {"role": "user", "content": prompt},
        ],
        json_mode=False,
    )


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
    ollama, memory, tools = build_runtime(settings)
    agent = AgentLoop(
        settings=settings,
        ollama=ollama,
        tools=tools,
        memory=memory,
        trace=print_trace,
    )
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


def _run_prompt_worker(state: ShellState) -> None:
    while True:
        job = state.job_queue.get()
        if job is None:
            break
        queued_prompt = job.prompt
        state.current_cancel.clear()
        state.prompt_active.set()
        try:
            attachment_context, attachment_paths = build_attachment_context(
                queued_prompt,
                state.settings.workspace,
            )
            if attachment_context:
                queued_prompt = f"{queued_prompt}\n\n{attachment_context}"
                state.transcript.write("attachments", {"paths": attachment_paths})
            if state.mode == "agent":
                state.history.append((state.mode, queued_prompt))
                state.transcript.write("user", {"mode": state.mode, "content": queued_prompt})
                agent_prompt = queued_prompt
                if state.plan_mode:
                    agent_prompt = "Plan only. Do not call tools. " + agent_prompt
                answer = state.agent_session.ask(
                    agent_prompt,
                    namespace=state.namespace,
                    cancel_event=state.current_cancel,
                )
                state.transcript.write("assistant", {"mode": state.mode, "content": answer[:4000]})
                if state.tui is not None:
                    print_raw(format_assistant_header())
                print_block(answer)
                continue

            state.history.append((state.mode, queued_prompt))
            state.transcript.write("user", {"mode": state.mode, "content": queued_prompt})
            chat_prompt = queued_prompt
            if state.plan_mode:
                chat_prompt = "Plan only. Do not claim actions were performed. " + chat_prompt
            state.chat_messages.append({"role": "user", "content": chat_prompt})
            streamed: list[str] = []
            print_raw(format_assistant_header() if state.tui is not None else "")

            def on_delta(delta: str) -> None:
                streamed.append(delta)
                print_delta(delta)

            answer = state.ollama.chat(
                state.chat_messages,
                json_mode=False,
                on_delta=on_delta,
                cancel_event=state.current_cancel,
            )
            state.chat_messages.append({"role": "assistant", "content": answer})
            state.transcript.write("assistant", {"mode": state.mode, "content": answer[:4000]})
            if streamed:
                print_raw("")
            else:
                print_block(answer)
        except OllamaCancelledError:
            state.transcript.write("cancel", {"job": job.id, "prompt": queued_prompt})
            print_block(f"cancelled job #{job.id}")
        except Exception as exc:
            console.print(f"[red]prompt failed:[/red] {type(exc).__name__}: {escape(str(exc))}")
        finally:
            state.prompt_active.clear()
            state.current_cancel.clear()
            state.job_queue.complete_current()


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
        memory=memory,
        namespace=namespace,
        trace=print_trace,
    )

    state = ShellState(
        settings=settings,
        ollama=ollama,
        memory=memory,
        tools=tools,
        agent_session=agent_session,
        transcript=transcript,
        job_queue=PromptJobQueue(),
        approval_policy=approval_policy,
        task=task,
        namespace=namespace,
        mode=mode,
        chat_messages=[
            {"role": "system", "content": build_chat_system_prompt(settings.workspace, settings.persona)}
        ],
    )

    prompt_session: PromptSession[str] | None = None
    original_console = console

    def status_line() -> str:
        return f"{state.settings.model} | context {context_percent(state.settings, state.agent_session, state.chat_messages)}%"

    ui_mode = os.getenv("AGENTX_TUI", "1").lower()
    if sys.stdin.isatty() and ui_mode not in {"0", "false", "classic"}:
        state.tui = AgentXTui(
            commands=SLASH_COMMANDS,
            status_text=status_line,
            full_screen=ui_mode in {"fullscreen", "full-screen"},
        )
        state.tui.start()
        console = Console(file=state.tui.writer, force_terminal=False, color_system=None, width=100)
    elif sys.stdin.isatty():
        prompt_session = PromptSession(
            completer=SlashCommandCompleter(SLASH_COMMANDS),
            complete_while_typing=True,
            erase_when_done=True,
            refresh_interval=0.2,
            bottom_toolbar=status_line,
        )

    worker = threading.Thread(
        target=_run_prompt_worker,
        args=(state,),
        name="agentx-prompt-worker",
        daemon=True,
    )
    worker.start()

    def wait_for_prompt_worker() -> None:
        while state.job_queue.current is not None or state.job_queue.pending_count() > 0:
            threading.Event().wait(0.05)

    def stop_prompt_worker() -> None:
        state.job_queue.stop()
        worker.join(timeout=5)

    console.print(
        Panel.fit(
            (
                f"model={state.settings.model} mode={state.mode} namespace={state.namespace}\n"
                + escape(slash_command_hint())
            ),
            title="agentX shell",
        )
    )

    try:
        while not state.should_exit:
            try:
                if state.tui is not None:
                    prompt = state.tui.prompt().strip()
                elif prompt_session is None:
                    prompt = typer.prompt("agentX").strip()
                else:
                    with patch_stdout(raw=True):
                        prompt = prompt_session.prompt("agentX: ").strip()
            except (EOFError, KeyboardInterrupt):
                wait_for_prompt_worker()
                finalize_session(state, None)
                console.print("\nbye")
                break

            if not prompt:
                continue
            if prompt_session is not None:
                print_block(f"agentX: {prompt}")

            head, _, _ = prompt.partition(" ")
            if head in SLASH_HANDLERS and head not in NON_BLOCKING_COMMANDS:
                wait_for_prompt_worker()

            if dispatch_slash(state, prompt):
                if state.should_exit:
                    wait_for_prompt_worker()
                    finalize_session(state, state.exit_reason)
                continue

            job = state.job_queue.submit(prompt)
            pending = state.job_queue.pending_count()
            if state.prompt_active.is_set() or pending > 1:
                console.print(f"[dim]queued job #{job.id}; pending={pending}[/dim]")
    finally:
        stop_prompt_worker()
        if state.tui is not None:
            state.tui.stop()
            console = original_console


if __name__ == "__main__":
    app()
