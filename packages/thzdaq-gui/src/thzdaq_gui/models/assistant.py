"""The assistant of the window: its model servers (ProvidersModel) and its chat
(AssistantModel), on QtCore.

A turn of the chat runs in a thread of its own (it waits for the model, for
the bench, for the person's consent); what it tells comes back to the GUI
thread as queued signals of the model, which owns the chat's items. Stop
ends the turn at once (Conversation.stop): what was still on its way from
the stopped turn is dropped.

The conversation is not kept: it ends with the window, while the
measurements it started go on in the daemon.
"""

import json
import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api.errors import LabError
from thzdaq_api.tools import Reach, tools

from thzdaq_gui.assistant.conversation import (
    MAX_STEPS,
    Conversation,
    Outcome,
    arguments,
)
from thzdaq_gui.assistant.keys import Keys
from thzdaq_gui.assistant.prompt import system_prompt
from thzdaq_gui.assistant.provider import (
    Client,
    Provider,
    ProviderError,
    ToolCall,
)
from thzdaq_gui.settings import ASSISTANT_PROVIDER, ASSISTANT_PROVIDERS, settings

NO_PROVIDER = "Add the server of a model first (the gear above)"
SHOWN = 40  # letters of an argument a card's line shows


class ProvidersModel(QObject):
    """The model servers the person added, the chosen one, and their keys
    (in the system's keyring, apart from the settings)."""

    changed = Signal()
    tested = Signal(str, bool, str)  # provider, it works, what was found

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keys = Keys()
        kept = settings().value(ASSISTANT_PROVIDERS)
        self._providers: List[Provider] = [
            Provider(**found) for found in json.loads(kept)
        ] if kept else []  # fmt: skip
        self._chosen: Optional[str] = settings().value(ASSISTANT_PROVIDER)

    def all(self) -> Tuple[Provider, ...]:
        return tuple(self._providers)

    def get(self, name: str) -> Optional[Provider]:
        return next((p for p in self._providers if p.name == name), None)

    def chosen(self) -> Optional[Provider]:
        """The one chosen, else the first one."""
        found = self.get(self._chosen) if self._chosen else None
        return found or (self._providers[0] if self._providers else None)

    def choose(self, name: str) -> None:
        self._chosen = name
        settings().setValue(ASSISTANT_PROVIDER, name)
        self.changed.emit()

    def key(self, name: str) -> Optional[str]:
        return self.keys.get(name)

    def save(self, provider: Provider, key: str, was: Optional[str] = None) -> None:
        """Add a provider, or change the one named was (its key moves with a
        new name)."""
        at = next(
            (
                i
                for i, p in enumerate(self._providers)
                if p.name in (was, provider.name)
            ),
            len(self._providers),
        )
        self._providers[at : at + 1] = [provider]
        if was is not None and was != provider.name:
            self.keys.forget(was)
            if self._chosen == was:
                self._chosen = provider.name
        self.keys.set(provider.name, key)
        self._store()

    def remove(self, name: str) -> None:
        self._providers = [p for p in self._providers if p.name != name]
        self.keys.forget(name)
        self._store()

    def test(self, provider: Provider, key: str) -> None:
        """Whether the server answers and takes tools; told by tested, from a
        thread of its own."""

        def run() -> None:
            try:
                self.tested.emit(provider.name, True, Client(provider, key).test())
            except ProviderError as e:
                self.tested.emit(provider.name, False, str(e))

        threading.Thread(target=run, name="provider test", daemon=True).start()

    def _store(self) -> None:
        kept = settings()
        kept.setValue(
            ASSISTANT_PROVIDERS, json.dumps([asdict(p) for p in self._providers])
        )
        if self._chosen is not None:
            kept.setValue(ASSISTANT_PROVIDER, self._chosen)
        self.changed.emit()


class Kind(str, Enum):
    PERSON = "person"  # what the person wrote
    ANSWER = "answer"  # what the model answered
    CALL = "call"  # a tool call: a card
    NOTE = "note"  # how a turn ended when it did not answer


class State(str, Enum):
    """Of a tool call."""

    RUNNING = "running"
    DONE = "done"
    REFUSED = "refused"  # refused or wrong: the model reads why
    STOPPED = "stopped"


@dataclass
class Item:
    """One thing in the chat."""

    kind: Kind
    text: str = ""  # the words; of a call, what it answered
    name: str = ""  # of a call: the tool
    arguments: Dict[str, Any] = field(default_factory=dict)
    state: State = State.DONE
    progress: Optional[Tuple[float, Optional[float]]] = None

    def summary(self) -> str:
        """A call in a line: the tool, its arguments' values and how it went
        ("set_quantity sis_bias_1 voltage_set 2.3 mV → done")."""
        values = " ".join(_shown(value) for value in self.arguments.values())
        head = f"{self.name} {values}".strip()
        if self.state is State.RUNNING and self.progress is not None:
            done, total = self.progress
            return f"{head} → {done:g}/{total:g}" if total else f"{head} → {done:g}"
        return f"{head} → {self.state.value}"


def _shown(value: Any) -> str:
    """An argument in the card's line: a long one (a script's text) cut."""
    if isinstance(value, dict):
        return " ".join(f"{k}={_shown(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ",".join(_shown(v) for v in value)
    text = " ".join(str(value).split())
    return text if len(text) <= SHOWN else text[: SHOWN - 1] + "…"


class _Turn:
    """What a turn tells, handed to the model's signals (queued: the turn
    runs in its own thread)."""

    def __init__(self, model: "AssistantModel", token: object):
        self.model, self.token = model, token

    def text(self, piece: str) -> None:
        self.model._text.emit(self.token, piece)

    def called(self, call: ToolCall) -> None:
        self.model._called.emit(self.token, call)

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        self.model._progress.emit(self.token, call, (done, total))

    def answered(self, call: str, text: str, failed: bool) -> None:
        self.model._answered.emit(self.token, call, text, failed)


class AssistantModel(QObject):
    added = Signal(int)  # an item, at its index
    item_changed = Signal(int)
    cleared = Signal()
    busy_changed = Signal(bool)

    # From the turn's thread, queued to the GUI thread: (turn, ...)
    _text = Signal(object, str)
    _called = Signal(object, object)
    _progress = Signal(object, str, object)
    _answered = Signal(object, str, str, bool)
    _ended = Signal(object, str, str)

    def __init__(self, session, providers: ProvidersModel, parent=None):
        super().__init__(parent)
        self.session = session
        self.providers = providers
        self.items: List[Item] = []
        self.conversation = Conversation()
        self._turn: Optional[object] = None
        self._answer: Optional[int] = None  # the item the model's words go to
        self._calls: Dict[str, int] = {}  # call id -> its item
        self._reach: Optional[Reach] = None
        self._reach_lock = threading.Lock()
        self._lab_changed = False  # the next turn reaches the lab anew
        self._text.connect(self._heard_text)
        self._called.connect(self._heard_call)
        self._progress.connect(self._heard_progress)
        self._answered.connect(self._heard_answer)
        self._ended.connect(self._heard_end)
        session.station_changed.connect(self._another_lab)
        session.config_changed.connect(self._bench_changed)

    def busy(self) -> bool:
        return self._turn is not None

    def send(self, text: str) -> None:
        """The person's message: the model answers it with the bench's tools."""
        text = text.strip()
        if not text or self.busy():
            return
        self._add(Item(Kind.PERSON, text))
        provider = self.providers.chosen()
        if provider is None:
            self._add(Item(Kind.NOTE, NO_PROVIDER))
            return
        client = Client(provider, self.providers.key(provider.name))
        conversation = self.conversation
        token = conversation.begin()
        self._turn, self._answer = token, None
        self.busy_changed.emit(True)
        listener = _Turn(self, token)
        folder = self.session.workspace

        def run() -> None:
            try:
                reach = self._reached()
            except LabError as e:
                conversation.stop()
                self._ended.emit(token, Outcome.FAILED.value, str(e))
                return
            outcome, why = conversation.say(
                token, text, client, tools(lambda: folder.folder), reach,
                system_prompt, listener,
            )  # fmt: skip
            self._ended.emit(token, outcome.value, why)

        threading.Thread(target=run, name="assistant", daemon=True).start()

    def stop(self) -> None:
        """End the turn now: its calls without an answer are stopped."""
        if self._turn is None:
            return
        self.conversation.stop()
        self._end(Outcome.STOPPED, "")

    def new_chat(self) -> None:
        """Forget the conversation (a turn running is stopped)."""
        self.stop()
        self.conversation = Conversation()
        self.items.clear()
        self.cleared.emit()

    def close(self) -> None:
        """The window closes: the turn stops, the assistant leaves the daemon."""
        self.stop()
        with self._reach_lock:
            if self._reach is not None:
                self._reach.close()
                self._reach = None

    def _reached(self) -> Reach:
        """The bench as the assistant: reached once, again after the window
        took another lab (in the turn's thread: it may wait for the daemon)."""
        with self._reach_lock:
            if self._lab_changed and self._reach is not None:
                self._reach.close()
                self._reach = None
            self._lab_changed = False
            if self._reach is None:
                self._reach = Reach(self.session.assistant_lab())
            return self._reach

    def _another_lab(self) -> None:
        with self._reach_lock:
            self._lab_changed = True
        self._bench_changed()

    def _bench_changed(self) -> None:
        """The model hears of the bench anew at the next turn."""
        self.conversation.forget_bench()

    # What the turn told, in the GUI thread
    def _heard_text(self, token: object, piece: str) -> None:
        if token is not self._turn:
            return
        if self._answer is None:
            self._answer = self._add(Item(Kind.ANSWER))
        self.items[self._answer].text += piece
        self.item_changed.emit(self._answer)

    def _heard_call(self, token: object, call: ToolCall) -> None:
        if token is not self._turn:
            return
        self._answer = None  # words after it go below it
        try:
            given = arguments(call)
        except LabError:  # the model reads why; the card shows none
            given = {}
        self._calls[call.id] = self._add(
            Item(Kind.CALL, name=call.name, arguments=given, state=State.RUNNING)
        )

    def _heard_progress(self, token: object, call: str, progress) -> None:
        if token is self._turn and call in self._calls:
            self.items[self._calls[call]].progress = progress
            self.item_changed.emit(self._calls[call])

    def _heard_answer(self, token: object, call: str, text: str, failed: bool):
        if token is not self._turn or call not in self._calls:
            return
        index = self._calls.pop(call)
        item = self.items[index]
        item.text, item.state = text, State.REFUSED if failed else State.DONE
        self.item_changed.emit(index)

    def _heard_end(self, token: object, outcome: str, why: str) -> None:
        if token is self._turn:
            self._end(Outcome(outcome), why)

    def _end(self, outcome: Outcome, why: str) -> None:
        for index in self._calls.values():
            self.items[index].state = State.STOPPED
            self.item_changed.emit(index)
        self._calls.clear()
        self._turn = self._answer = None
        note = {
            Outcome.STOPPED: "Stopped.",
            Outcome.STEPS: f"Stopped after {MAX_STEPS} steps: say “go on” to continue.",
            Outcome.FAILED: why,
        }.get(outcome)
        if note:
            self._add(Item(Kind.NOTE, note))
        self.busy_changed.emit(False)

    def _add(self, item: Item) -> int:
        self.items.append(item)
        self.added.emit(len(self.items) - 1)
        return len(self.items) - 1
