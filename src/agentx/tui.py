from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Mapping

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.widgets.base import Frame
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from agentx.prompting import SlashCommandCompleter


def format_user_message(text: str) -> str:
    return f"\n--- Maki ------------------------------------------------------------\n{text}\n"


def format_assistant_header() -> str:
    return "\n--- agentX ----------------------------------------------------------\n"


class AgentXTuiWriter:
    def __init__(self, tui: "AgentXTui") -> None:
        self.tui = tui

    def write(self, data: str) -> int:
        if data:
            self.tui.write(data)
        return len(data)

    def flush(self) -> None:
        return


class AgentXTui:
    def __init__(
        self,
        *,
        command_catalog: list[Mapping[str, object]],
        status_text: Callable[[], str],
        full_screen: bool = False,
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
            completer=SlashCommandCompleter(catalog=command_catalog),
            complete_while_typing=True,
            accept_handler=self._accept_input,
        )
        status = Window(
            height=1,
            content=FormattedTextControl(lambda: [("reverse", f" {self._status_text()} ")]),
        )

        # 輸入框加上線框 + 上方多一點 margin（使用者要求）
        input_frame = Frame(self.input)

        # 注意：不要對包含 Frame 的容器強制小 height，否則 terminal 太小時會報 "Window too small..."


        key_bindings = KeyBindings()

        @key_bindings.add("c-c")
        def _(event: object) -> None:
            self.input.buffer.reset()

        @key_bindings.add("c-d")
        def _(event: object) -> None:
            self._input_queue.put("/exit")

        self.app: Application[None] = Application(
            layout=Layout(
                HSplit(
                    [
                        self.output,
                        status,
                        Window(height=1),   # 額外 margin-up，讓輸入框跟狀態列有呼吸空間
                        input_frame,
                    ]
                ),
                focused_element=self.input,
            ),
            key_bindings=key_bindings,
            full_screen=full_screen,
            refresh_interval=0.2,
            mouse_support=False,
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
            self.write(format_user_message(text))
            self._input_queue.put(text)
        return True
