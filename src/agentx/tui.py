from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from agentx.prompting import SlashCommandCompleter


class AgentXTuiWriter:
    def __init__(self, tui: "AgentXTui") -> None:
        self.tui = tui

    def write(self, data: str) -> int:
        if data:
            self.tui.write(data.rstrip("\n"))
        return len(data)

    def flush(self) -> None:
        return


class AgentXTui:
    def __init__(
        self,
        *,
        commands: list[tuple[str, str]],
        status_text: Callable[[], str],
    ) -> None:
        self._input_queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._status_text = status_text
        self.output = TextArea(
            text="",
            read_only=True,
            scrollbar=True,
            wrap_lines=True,
            focusable=False,
        )
        self.input = TextArea(
            height=1,
            multiline=False,
            prompt="agentX: ",
            completer=SlashCommandCompleter(commands),
            complete_while_typing=True,
            accept_handler=self._accept_input,
        )
        status = Window(
            height=1,
            content=FormattedTextControl(lambda: [("reverse", f" {self._status_text()} ")]),
        )
        key_bindings = KeyBindings()

        @key_bindings.add("c-c")
        def _(event: object) -> None:
            self.input.buffer.reset()

        @key_bindings.add("c-d")
        def _(event: object) -> None:
            self._input_queue.put("/exit")

        self.app: Application[None] = Application(
            layout=Layout(HSplit([self.output, status, self.input]), focused_element=self.input),
            key_bindings=key_bindings,
            full_screen=True,
            refresh_interval=0.2,
            mouse_support=True,
        )
        self.writer = AgentXTuiWriter(self)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.app.run, name="agentx-tui", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.app.exit()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def prompt(self) -> str:
        return self._input_queue.get()

    def write(self, text: object) -> None:
        content = str(text)
        if not content:
            return
        with self._lock:
            self.output.text += content
            self.output.buffer.cursor_position = len(self.output.text)
        self.app.invalidate()

    def _accept_input(self, buffer: object) -> bool:
        text = getattr(buffer, "text", "").strip()
        getattr(buffer, "reset")()
        if text:
            self.write(f"agentX: {text}")
            self._input_queue.put(text)
        return True
