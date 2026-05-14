from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


def slash_completion_text(command: str) -> str:
    parts: list[str] = []
    for part in command.split():
        if part.startswith("[") or part.isupper():
            break
        parts.append(part)
    text = " ".join(parts)
    if len(parts) < len(command.split()):
        text += " "
    return text


class SlashCommandCompleter(Completer):
    def __init__(self, commands: Iterable[tuple[str, str]]) -> None:
        self._commands = [
            (slash_completion_text(command), command, description) for command, description in commands
        ]

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for completion_text, display, description in self._commands:
            if completion_text.startswith(text):
                yield Completion(
                    completion_text,
                    start_position=-len(text),
                    display=display,
                    display_meta=description,
                )
