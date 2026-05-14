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
            console.print(agent_session.ask(prompt, namespace=namespace))
            continue

        chat_messages.append({"role": "user", "content": prompt})
        answer = ollama.chat(chat_messages, json_mode=False)
        chat_messages.append({"role": "assistant", "content": answer})
        console.print(answer)


if __name__ == "__main__":
    app()
