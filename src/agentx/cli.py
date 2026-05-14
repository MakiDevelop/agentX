from __future__ import annotations

from dataclasses import replace

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agentx.config import Settings
from agentx.loop import AgentLoop, AgentSession
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.tools import ToolRegistry

app = typer.Typer(help="agentX local Ollama agent shell.", no_args_is_help=True)
console = Console()

SLASH_COMMANDS = [
    ("/help", "列出所有 slash command 與中文說明"),
    ("/tools", "列出 agent 模式可用工具與中文說明"),
    ("/context", "顯示目前 agent 上下文使用量與壓縮次數"),
    ("/compact", "壓縮目前 agent session 上下文，保留最近訊息摘要"),
    ("/history", "顯示本輪 shell 的簡短互動紀錄"),
    ("/files [PATH]", "列出 repo 檔案，預設目前 workspace"),
    ("/read PATH", "讀取 repo 內指定檔案"),
    ("/search PATTERN", "在 repo 內搜尋文字"),
    ("/git", "顯示 git status"),
    ("/diff [PATH]", "顯示 git diff，可指定單一檔案"),
    ("/memory QUERY", "查詢目前 namespace 的 Memory Hall 記憶"),
    ("/test", "執行固定 allowlist 驗證：ruff check 與 pytest"),
    ("/plan", "切換 plan 模式；plan 模式只討論方案，不使用工具"),
    ("/mode chat", "切換到純聊天模式，不使用工具，速度較快"),
    ("/mode agent", "切換到 agent 工具模式，可使用 repo / git / Memory Hall 工具"),
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


def print_tool_result(result_text: str) -> None:
    console.print(result_text if result_text.strip() else "[dim](no output)[/dim]")


@app.callback()
def main() -> None:
    """Run local Ollama agent workflows."""


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Task or question for agentX."),
    namespace: str = typer.Option("project:agentX", help="Default Memory Hall namespace."),
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
) -> None:
    settings = Settings()
    if max_steps is not None:
        settings = replace(settings, max_steps=max_steps)
    ollama = OllamaClient(
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    memory = MemoryHallClient(
        base_url=settings.memory_hall_url,
        token=settings.memory_hall_token,
    )
    tools = ToolRegistry(workspace=settings.workspace, memory=memory)
    agent = AgentLoop(settings=settings, ollama=ollama, tools=tools, trace=print_trace)
    console.print(agent.run(prompt, namespace=namespace))


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="Plain chat prompt for the Ollama model."),
) -> None:
    """Call Ollama directly without tool JSON mode."""
    settings = Settings()
    ollama = OllamaClient(
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
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
    namespace: str = typer.Option("project:agentX", help="Default Memory Hall namespace."),
    mode: str = typer.Option("chat", help="Start mode: chat or agent."),
    max_steps: int | None = typer.Option(None, help="Override max agent loop steps."),
) -> None:
    """Start an interactive agentX session."""
    settings = Settings()
    if max_steps is not None:
        settings = replace(settings, max_steps=max_steps)
    ollama = OllamaClient(
        base_url=settings.ollama_url,
        model=settings.model,
        timeout=settings.ollama_timeout,
    )
    memory = MemoryHallClient(
        base_url=settings.memory_hall_url,
        token=settings.memory_hall_token,
    )
    tools = ToolRegistry(workspace=settings.workspace, memory=memory)
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

    console.print(
        Panel.fit(
            (
                f"model={settings.model} mode={mode} namespace={namespace}\n"
                + slash_command_hint()
            ),
            title="agentX shell",
        )
    )

    while True:
        try:
            prompt = typer.prompt("agentX").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye")
            break

        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            break
        if prompt == "/help":
            print_slash_help()
            continue
        if prompt == "/tools":
            print_tools(tools)
            continue
        if prompt == "/context":
            print_context(agent_session, chat_messages)
            continue
        if prompt == "/compact":
            console.print(agent_session.compact())
            continue
        if prompt == "/history":
            print_history(history)
            continue
        if prompt.startswith("/files"):
            path = prompt.removeprefix("/files").strip() or "."
            result = tools.run("list_files", {"path": path})
            print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
            continue
        if prompt.startswith("/read "):
            path = prompt.removeprefix("/read ").strip()
            result = tools.run("read_file", {"path": path})
            print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
            continue
        if prompt.startswith("/search "):
            pattern = prompt.removeprefix("/search ").strip()
            result = tools.run("search_text", {"pattern": pattern})
            print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
            continue
        if prompt == "/git":
            result = tools.run("git_status", {})
            print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
            continue
        if prompt.startswith("/diff"):
            path = prompt.removeprefix("/diff").strip()
            args = {"path": path} if path else {}
            result = tools.run("git_diff", args)
            print_tool_result(result.content if result.ok else f"工具執行失敗：{result.content}")
            continue
        if prompt.startswith("/memory "):
            query = prompt.removeprefix("/memory ").strip()
            result = tools.run("memory_search", {"query": query, "namespace": namespace})
            print_tool_result(result.content if result.ok else f"memory search failed: {result.content}")
            continue
        if prompt == "/test":
            result = tools.run("run_tests", {})
            print_tool_result(result.content if result.ok else f"驗證失敗：{result.content}")
            continue
        if prompt == "/plan":
            plan_mode = not plan_mode
            console.print(f"plan={'on' if plan_mode else 'off'}")
            continue
        if prompt.startswith("/remember "):
            content = prompt.removeprefix("/remember ").strip()
            if not content:
                console.print("usage: /remember 要寫入 Memory Hall 的內容")
                continue
            result = tools.run("memory_write", {"content": content, "namespace": namespace})
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
            console.print(f"mode={mode}")
            continue
        if prompt.startswith("/model "):
            model = prompt.removeprefix("/model ").strip()
            if not model:
                console.print("usage: /model gemma4:e2b")
                continue
            settings = replace(settings, model=model)
            ollama = OllamaClient(
                base_url=settings.ollama_url,
                model=settings.model,
                timeout=settings.ollama_timeout,
            )
            agent_session.ollama = ollama
            console.print(f"model={settings.model}")
            continue
        if prompt == "/status":
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
            console.print("cleared")
            continue

        if mode == "agent":
            history.append((mode, prompt))
            if plan_mode:
                prompt = "Plan only. Do not call tools. " + prompt
            console.print(agent_session.ask(prompt, namespace=namespace))
            continue

        history.append((mode, prompt))
        if plan_mode:
            prompt = "Plan only. Do not claim actions were performed. " + prompt
        chat_messages.append({"role": "user", "content": prompt})
        answer = ollama.chat(chat_messages, json_mode=False)
        chat_messages.append({"role": "assistant", "content": answer})
        console.print(answer)


if __name__ == "__main__":
    app()
