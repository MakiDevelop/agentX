from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

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


@dataclass(frozen=True)
class SlashCompletionItem:
    text: str
    display: str
    description: str
    risk: str = "GREEN - read-only, local display, or low-risk routing"
    examples: tuple[str, ...] = ()
    related: tuple[str, ...] = ()

    @property
    def meta(self) -> str:
        risk_label = self.risk.split(" - ", 1)[0]
        example = f" · e.g. {self.examples[0]}" if self.examples else ""
        return f"{risk_label} · {self.description}{example}"


def slash_completion_items_from_catalog(
    catalog: Iterable[Mapping[str, object]],
) -> list[SlashCompletionItem]:
    items: list[SlashCompletionItem] = []
    for entry in catalog:
        usage = str(entry["usage"])
        items.append(
            SlashCompletionItem(
                text=slash_completion_text(usage),
                display=usage,
                description=str(entry["description"]),
                risk=str(entry.get("risk", "GREEN - read-only, local display, or low-risk routing")),
                examples=tuple(str(example) for example in entry.get("examples", ())),
                related=tuple(str(command) for command in entry.get("related", ())),
            )
        )
    return items


def slash_completion_items_from_pairs(
    commands: Iterable[tuple[str, str]],
) -> list[SlashCompletionItem]:
    return [
        SlashCompletionItem(
            text=slash_completion_text(command),
            display=command,
            description=description,
        )
        for command, description in commands
    ]


class SlashCommandCompleter(Completer):
    def __init__(
        self,
        commands: Iterable[tuple[str, str]] | None = None,
        *,
        catalog: Iterable[Mapping[str, object]] | None = None,
    ) -> None:
        if catalog is not None:
            self._commands = slash_completion_items_from_catalog(catalog)
        else:
            self._commands = slash_completion_items_from_pairs(commands or ())

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for item in self._commands:
            if item.text.startswith(text):
                yield Completion(
                    item.text,
                    start_position=-len(text),
                    display=item.display,
                    display_meta=item.meta,
                )
