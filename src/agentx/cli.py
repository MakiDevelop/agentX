from __future__ import annotations

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
) -> None:
    settings = Settings()
    ollama = OllamaClient(base_url=settings.ollama_url, model=settings.model)
    memory = MemoryHallClient(
        base_url=settings.memory_hall_url,
        token=settings.memory_hall_token,
    )
    tools = ToolRegistry(workspace=settings.workspace, memory=memory)
    agent = AgentLoop(settings=settings, ollama=ollama, tools=tools)
    console.print(agent.run(prompt, namespace=namespace))


if __name__ == "__main__":
    app()
