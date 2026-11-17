"""The built-in assistant as a chat of the dock (chat.Chat): a conversation
(conversation.py) with the model's server chosen (provider.py) and the
bench's tools (thzdaq_api.tools), reached as the assistant. No Qt.

A turn runs in a thread of its own. The bench is reached there, once, and
again after the window took another lab: the GUI thread only marks that, and
the lock that guards the reach is never held while the daemon is asked. The
system prompt is made with the person's instructions as they were when the
turn began.
"""

import threading
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence

from thzdaq_api.errors import LabError
from thzdaq_api.lab import Lab
from thzdaq_api.tools import Reach, tools

from thzdaq_gui.assistant.attachments import content
from thzdaq_gui.assistant.chat import (
    Chat,
    Choice,
    Listener,
    Outcome,
    Said,
    Unready,
)
from thzdaq_gui.assistant.conversation import Conversation
from thzdaq_gui.assistant.prompt import system_prompt
from thzdaq_gui.assistant.provider import Client, Provider

TITLE = "Assistant"
NO_PROVIDER = "Add the server of a model first (the gear above)"


class Servers(Protocol):
    """The model servers the person added and the one chosen
    (models/assistant.py, ProvidersModel)."""

    def all(self) -> Sequence[Provider]:
        ...

    def chosen(self) -> Optional[Provider]:
        ...

    def choose(self, name: str) -> None:
        ...

    def key(self, name: str) -> Optional[str]:
        ...


class Instructions(Protocol):
    """The person's instructions to the assistant (InstructionsModel)."""

    def instructions(self) -> str:
        ...


class Workspace(Protocol):
    folder: Optional[Path]


class Window(Protocol):
    """The window's session, as the chat needs it: its workspace (where a
    measurement goes), its id (what the assistant shows goes to it), and the
    lab called as its assistant."""

    workspace: Workspace
    window: Optional[str]

    def assistant_lab(self) -> Lab:
        ...


class BuiltInChat(Chat):
    title = TITLE

    def __init__(self, session: Window, servers: Servers, instructions: Instructions):
        self.session = session
        self.servers = servers
        self.instructions = instructions
        self.conversation = Conversation()
        self._changed: Callable[[], None] = lambda: None
        # The bench as the assistant; the lock only guards these, never a wait
        self._reach: Optional[Reach] = None
        self._reach_lock = threading.Lock()
        self._lab_changed = False  # the next turn reaches the lab anew
        self._closed = False

    def start(self, said: Optional[Said], listener: Listener) -> None:
        provider = self.servers.chosen()
        if provider is None:
            raise Unready(NO_PROVIDER)
        client = Client(provider, self.servers.key(provider.name))
        message = None if said is None else content(said.text, said.attachments)
        conversation = self.conversation
        token = conversation.begin()
        folder = self.session.workspace
        window = self.session.window  # what it shows goes to its own window
        instructions = self.instructions.instructions()

        def prompt(reach: Reach) -> str:
            return system_prompt(reach, instructions)

        def run() -> None:
            try:
                reach = self._reached()
            except LabError as e:
                conversation.stop()
                listener.ended(Outcome.FAILED, str(e))
                return
            outcome, why = conversation.say(
                token, message, client,
                tools(lambda: folder.folder, lambda: window), reach,
                prompt, listener,
            )  # fmt: skip
            listener.ended(outcome, why)

        threading.Thread(target=run, name="assistant", daemon=True).start()

    def queue(self, said: Said) -> None:
        self.conversation.queue(content(said.text, said.attachments))

    def stop(self) -> None:
        self.conversation.stop()

    def new_chat(self) -> None:
        self.conversation = Conversation()

    def close(self) -> None:
        """The assistant leaves the daemon."""
        with self._reach_lock:
            self._closed = True
            reach, self._reach = self._reach, None
        if reach is not None:
            reach.close()

    def lab_changed(self) -> None:
        with self._reach_lock:
            self._lab_changed = True
        self.prompt_changed()

    def prompt_changed(self) -> None:
        self.conversation.forget_bench()

    def models(self) -> Sequence[Choice]:
        return tuple(
            Choice(p.name, p.name, f"{p.model} at {p.url}") for p in self.servers.all()
        )

    def model(self) -> Optional[str]:
        chosen = self.servers.chosen()
        return chosen.name if chosen is not None else None

    def choose(self, model: str) -> None:
        self.servers.choose(model)

    def context_limit(self) -> Optional[int]:
        chosen = self.servers.chosen()
        return chosen.context if chosen is not None else None

    def watch(self, changed: Callable[[], None]) -> None:
        self._changed = changed

    def servers_changed(self) -> None:
        """The servers, the one chosen or what is known of its model changed
        (the window's settings, in the GUI thread)."""
        self._changed()

    def _reached(self) -> Reach:
        """The bench as the assistant: reached once, again after the window
        took another lab. In the turn's thread, and outside the lock: it may
        wait for the daemon, the GUI thread only marks another lab."""
        with self._reach_lock:
            stale = self._reach if self._lab_changed else None
            if self._lab_changed:
                self._reach, self._lab_changed = None, False
            reach = self._reach
        if stale is not None:
            stale.close()
        if reach is not None:
            return reach
        reach = Reach(self.session.assistant_lab())
        with self._reach_lock:
            if self._closed:
                extra = reach  # the window closed meanwhile
            elif self._reach is None:
                self._reach, extra = reach, None
            else:  # a stopped turn reached it meanwhile
                reach, extra = self._reach, reach
        if extra is not None:
            extra.close()
        return reach
