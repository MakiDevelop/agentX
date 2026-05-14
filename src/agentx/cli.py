from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agentx.approval import ApprovalMode, ApprovalPolicy
from agentx.config import Settings
from agentx.doctor import run_doctor
from agentx.git_workflow import build_commit_plan, commit_and_push
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.prompting import SlashCommandCompleter
from agentx.project_config import load_project_config, set_project_config
from agentx.project_profile import build_project_profile
from agentx.safety import Risk
from agentx.task import TaskState, clear_task, finish_task, load_task, start_task
from agentx.tools import ToolRegistry
from agentx.transcript import Transcript, find_transcript, list_transcripts, summarize_transcript

app = typer.Typer(
    help="agentX local Ollama agent shell.",
    no_args_is_help=True,
    invoke_without_command=True,
)
console = Console()

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
    ("/sessions", "列出最近 transcript，可搭配 /resume"),
    ("/transcript", "顯示本輪 JSONL transcript 檔案路徑"),
    ("/handoff [TEXT]", "寫入 Memory Hall 交接摘要；未提供文字時自動整理本輪紀錄"),
    ("/resume [latest|FILE]", "從 JSONL transcript 載入最近上下文摘要"),
    ("/files [PATH]", "列出 repo 檔案，預設目前 workspace"),
    ("/read PATH", "讀取 repo 內指定檔案"),
    ("/search PATTERN", "在 repo 內搜尋文字"),
    ("/git", "顯示 git status"),
    ("/diff [PATH]", "顯示 git diff，可指定單一檔案"),
    ("/apply PATCH_FILE", "套用 workspace 內 patch 檔，會先要求 approval"),
    ("/approval [ask|auto|off]", "查看或切換 YELLOW 工具 approval policy"),
    ("/memory QUERY", "查詢目前 namespace 的 Memory Hall 記憶"),
    ("/run COMMAND", "執行固定 allowlist 命令"),
    ("/test", "執行固定 allowlist 驗證：ruff check 與 pytest"),
    ("/review", "收集 git diff 與測試結果，輸出 findings-first review"),
    ("/commit [MESSAGE]", "跑測試後逐檔 stage、中文 commit 並 push"),
    ("/plan", "切換 plan 模式；plan 模式只討論方案，不使用工具"),
    ("/mode chat", "切換到純聊天模式，不使用工具，速度較快"),
    ("/mode agent", "切換到 agent 工具模式，可使用 repo / git / Memory Hall 工具"),
    ("/models", "列出 Ollama 目前可用模型"),
    ("/model MODEL", "切換 Ollama 模型，例如 /model gemma4:31b"),
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


def print_history(history: list[tuple[str, str]]) -> None:
    table = Table(title="agentX session history", show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Mode", style="cyan", no_wrap=True)
    table.add_column("Prompt")
    for index, (mode, prompt) in enumerate(history[-20:], start=max(1, len(history) - 19)):
        table.add_row(str(index), mode, prompt[:120])
    console.print(table)


def print_sessions(settings: Settings) -> None:
    table = Table(title="agentX sessions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    for path in list_transcripts(settings.workspace):
        table.add_row(path.stem, str(path))
    console.print(table)


def print_tool_result(result_text: str) -> None:
    console.print(result_text if result_text.strip() else "[dim](no output)[/dim]")


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
    table.add_row("auto_handoff", str(settings.auto_handoff))
    project_config = load_project_config(settings.workspace)
    table.add_row("config_file_model", str(project_config.model))
    table.add_row("config_file_namespace", str(project_config.namespace))
    table.add_row("config_file_mode", str(project_config.mode))
    table.add_row("config_file_approval", str(project_config.approval))
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
    console.print(plan.status)
    console.print("git diff --stat:")
    console.print(plan.diff_stat or "(no tracked diff stat; maybe untracked files only)")
    console.print("files to stage one by one:")
    for path in plan.files:
        console.print(f"- {path}")
    console.print("tests:")
    console.print(tests.content)

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
    namespace: str | None = typer.Option(None, "--namespace", help="Memory Hall namespace for -p."),
) -> None:
    """Run local Ollama agent workflows."""
    if print_prompt is None:
        return
    if ctx.invoked_subcommand is not None:
        return
    console.print(run_print_prompt(print_prompt, namespace=namespace, agent_mode=agent))
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


def run_print_prompt(prompt: str, namespace: str | None, agent_mode: bool = False) -> str:
    settings = Settings()
    project_config = load_project_config(settings.workspace)
    namespace = namespace or project_config.namespace or "project:agentX"
    ollama, _, tools = build_runtime(settings)
    if agent_mode:
        agent_loop = AgentLoop(settings=settings, ollama=ollama, tools=tools, namespace=namespace)
        return agent_loop.run(prompt, namespace=namespace)
    return ollama.chat(
        [
            {"role": "system", "content": "Use Traditional Chinese. Answer concisely."},
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
    console.print(agent.run(prompt, namespace=namespace))


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="Plain chat prompt for the Ollama model."),
) -> None:
    """Call Ollama directly without tool JSON mode."""
    settings = Settings()
    ollama, _, _ = build_runtime(settings)
    answer = ollama.chat(
        [
            {"role": "system", "content": "Use Traditional Chinese. Answer concisely."},
            {"role": "user", "content": prompt},
        ],
        json_mode=False,
    )
    console.print(answer)


@app.command()
def shell(
    namespace: str | None = typer.Option(None, help="Default Memory Hall namespace."),
    mode: str | None = typer.Option(None, help="Start mode: chat or agent."),
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
) -> None:
    """Start an interactive agentX session."""
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
    chat_messages = [{"role": "system", "content": "Use Traditional Chinese. Answer concisely."}]
    history: list[tuple[str, str]] = []
    plan_mode = False
    prompt_queue: queue.Queue[str | None] = queue.Queue()
    prompt_active = threading.Event()
    prompt_session: PromptSession[str] | None = None
    if sys.stdin.isatty():
        prompt_session = PromptSession(
            completer=SlashCommandCompleter(SLASH_COMMANDS),
            complete_while_typing=True,
        )

    def run_prompt_worker() -> None:
        nonlocal chat_messages
        while True:
            queued_prompt = prompt_queue.get()
            if queued_prompt is None:
                prompt_queue.task_done()
                break
            prompt_active.set()
            try:
                if mode == "agent":
                    history.append((mode, queued_prompt))
                    transcript.write("user", {"mode": mode, "content": queued_prompt})
                    agent_prompt = queued_prompt
                    if plan_mode:
                        agent_prompt = "Plan only. Do not call tools. " + agent_prompt
                    answer = agent_session.ask(agent_prompt, namespace=namespace)
                    transcript.write("assistant", {"mode": mode, "content": answer[:4000]})
                    console.print(answer)
                    continue

                history.append((mode, queued_prompt))
                transcript.write("user", {"mode": mode, "content": queued_prompt})
                chat_prompt = queued_prompt
                if plan_mode:
                    chat_prompt = "Plan only. Do not claim actions were performed. " + chat_prompt
                chat_messages.append({"role": "user", "content": chat_prompt})
                answer = ollama.chat(chat_messages, json_mode=False)
                chat_messages.append({"role": "assistant", "content": answer})
                transcript.write("assistant", {"mode": mode, "content": answer[:4000]})
                console.print(answer)
            except Exception as exc:
                console.print(f"[red]prompt failed:[/red] {type(exc).__name__}: {escape(str(exc))}")
            finally:
                prompt_active.clear()
                prompt_queue.task_done()

    worker = threading.Thread(target=run_prompt_worker, name="agentx-prompt-worker", daemon=True)
    worker.start()

    def wait_for_prompt_worker() -> None:
        prompt_queue.join()

    def stop_prompt_worker() -> None:
        prompt_queue.put(None)
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
                if prompt_session is None:
                    prompt = typer.prompt("agentX").strip()
                else:
                    with patch_stdout():
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
                    console.print(f"\n{message}")
                console.print("\nbye")
                break

            if not prompt:
                continue
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
                    console.print(message)
                transcript.write("session_end", {"reason": prompt})
                break
            if prompt.startswith("/"):
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
                console.print(updated)
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
                console.print(output)
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
                console.print(result)
                continue
            if prompt == "/history":
                transcript.write("slash_command", {"command": prompt})
                print_history(history)
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
                console.print(message)
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
            if prompt.startswith("/search "):
                pattern = prompt.removeprefix("/search ").strip()
                result = tools.run("search_text", {"pattern": pattern})
                transcript.write(
                    "tool",
                    {"command": "/search", "pattern": pattern, "ok": result.ok, "content": result.content[:2000]},
                )
                print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
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
            if prompt == "/test":
                result = tools.run("run_tests", {})
                transcript.write("tool", {"command": "/test", "ok": result.ok, "content": result.content[:4000]})
                print_tool_result(result.content if result.ok else f"驗證失敗：{result.content}")
                continue
            if prompt == "/review":
                transcript.write("slash_command", {"command": prompt})
                output = run_review(ollama, tools)
                transcript.write("review", {"content": output[:4000]})
                console.print(output)
                continue
            if prompt.startswith("/commit"):
                message = prompt.removeprefix("/commit").strip() or None
                transcript.write("slash_command", {"command": prompt})
                output = run_commit_flow(settings, tools, message)
                transcript.write("commit", {"message": message, "content": output[:4000]})
                console.print(output)
                continue
            if prompt == "/plan":
                plan_mode = not plan_mode
                transcript.write("slash_command", {"command": prompt, "plan": plan_mode})
                console.print(f"plan={'on' if plan_mode else 'off'}")
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
            if prompt == "/status":
                transcript.write("slash_command", {"command": prompt})
                approx_tokens = agent_session.context_chars // 4
                console.print(
                    f"model={settings.model} mode={mode} namespace={namespace} "
                    f"agent_messages={agent_session.message_count} "
                    f"agent_context~{approx_tokens} tokens chat_messages={len(chat_messages)}"
                )
                continue
            if prompt == "/clear":
                agent_session.clear()
                chat_messages = [{"role": "system", "content": "Use Traditional Chinese. Answer concisely."}]
                transcript.write("slash_command", {"command": prompt})
                console.print("cleared")
                continue

            prompt_queue.put(prompt)
            pending = prompt_queue.qsize()
            if prompt_active.is_set() or pending > 1:
                console.print(f"[dim]queued prompt; pending={pending}[/dim]")
    finally:
        stop_prompt_worker()


if __name__ == "__main__":
    app()
