from __future__ import annotations

from dataclasses import replace

import typer
from rich.console import Console

from agentx.config import Settings
from agentx.loop import AgentLoop
from agentx.memory_hall import MemoryHallClient
from agentx.ollama import OllamaClient
from agentx.tools import ToolRegistry

app = typer.Typer(help="agentX local Ollama agent shell.", no_args_is_help=True)
console = Console()


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
    agent = AgentLoop(settings=settings, ollama=ollama, tools=tools)
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


if __name__ == "__main__":
    app()
