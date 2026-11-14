"""The assistant of the window: its model servers (ProvidersModel) and its chat
(AssistantModel), on QtCore.

A turn of the chat runs in a thread of its own (it waits for the model, for
the bench, for the person's consent); what it tells comes back to the GUI
thread as queued signals of the model, which owns the chat's items. Stop
ends the turn at once (Conversation.stop): what was still on its way from
the stopped turn is dropped.

What the person sends while a turn runs waits and joins at the turn's next
step (queued, then sent). The model tells what the turn does now (phase:
thinking, writing, running a tool), how long it runs, what the model thought
(a card that folds), and the tokens: of each turn, of the chat, and how much
of the model's context the conversation fills.

The conversation is not kept: it ends with the window, while the
measurements it started go on in the daemon.
"""

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api.errors import LabError
from thzdaq_api.tools import Reach, tools

from thzdaq_gui.assistant.attachments import Attachment, Content, content
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
    Usage,
)
from thzdaq_gui.settings import ASSISTANT_PROVIDER, ASSISTANT_PROVIDERS, settings

NO_PROVIDER = "Add the server of a model first (the gear above)"
SHOWN = 40  # letters of an argument a card's line shows
# What a turn does now
THINKING, WRITING, RUNNING = "Thinking", "Writing", "Running"


class ProvidersModel(QObject):
    """The model servers the person added, the chosen one, and their keys
    (in the system's keyring, apart from the settings)."""

    changed = Signal()
    tested = Signal(str, bool, str)  # provider, it works, what was found
    context_found = Signal(str, int)  # provider, its model's tokens (0: unknown)

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
        thread of its own, after context_found: the tokens its model takes
        as the server tells them."""

        def run() -> None:
            client = Client(provider, key)
            try:
                told = client.test()
            except ProviderError as e:
                self.tested.emit(provider.name, False, str(e))
                return
            self.context_found.emit(provider.name, client.context() or 0)
            self.tested.emit(provider.name, True, told)

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
    THOUGHT = "thought"  # what the model thought before: a card
    CALL = "call"  # a tool call: a card
    NOTE = "note"  # how a turn ended when it did not answer
    STATS = "stats"  # how long a turn took and its tokens


class State(str, Enum):
    """Of a tool call, or of a thought."""

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
    attachments: Tuple[Attachment, ...] = ()  # of the person's
    queued: bool = False  # the person's: waits for the turn's next step
    unsent: bool = False  # the person's: dropped by a stop before it went
    started: float = 0.0  # of a thought: when (time.monotonic)
    seconds: Optional[float] = None  # of a thought: how long, once over

    def summary(self) -> str:
        """A call in a line: the tool, its arguments' values and how it went
        ("set_quantity sis_bias_1 voltage_set 2.3 mV → done")."""
        values = " ".join(_shown(value) for value in self.arguments.values())
        head = f"{self.name} {values}".strip()
        if self.state is State.RUNNING and self.progress is not None:
            done, total = self.progress
            return f"{head} → {done:g}/{total:g}" if total else f"{head} → {done:g}"
        return f"{head} → {self.state.value}"

    def thought_title(self) -> str:
        """A thought in a line: thinking now, or for how long it thought."""
        if self.seconds is None:
            return f"{THINKING}… {time.monotonic() - self.started:.0f} s"
        return f"Thought for {self.seconds:.0f} s"


def _shown(value: Any) -> str:
    """An argument in the card's line: a long one (a script's text) cut."""
    if isinstance(value, dict):
        return " ".join(f"{k}={_shown(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ",".join(_shown(v) for v in value)
    text = " ".join(str(value).split())
    return text if len(text) <= SHOWN else text[: SHOWN - 1] + "…"


def tokens(count: int) -> str:
    """1234 -> 1.2k"""
    if count < 1000:
        return str(count)
    return f"{count / 1000:.1f}k" if count < 100_000 else f"{count // 1000}k"


@dataclass
class Tokens:
    """Tokens summed over steps; context: what the last step's model read
    and wrote, the conversation's size as the model sees it."""

    read: int = 0
    written: int = 0
    reasoning: int = 0
    steps: int = 0
    context: int = 0

    def add(self, usage: Usage) -> None:
        self.read += usage.prompt
        self.written += usage.completion
        self.reasoning += usage.reasoning
        self.context = usage.prompt + usage.completion

    def told(self) -> str:
        """In a line: "4.2k in · 310 out (120 thinking)"."""
        if not (self.read or self.written):
            return ""
        thinking = f" ({tokens(self.reasoning)} thinking)" if self.reasoning else ""
        return f"{tokens(self.read)} in · {tokens(self.written)} out{thinking}"


class _Turn:
    """What a turn tells, handed to the model's signals (queued: the turn
    runs in its own thread)."""

    def __init__(self, model: "AssistantModel", token: object):
        self.model, self.token = model, token

    def asking(self) -> None:
        self.model._asking.emit(self.token)

    def taken(self, count: int) -> None:
        self.model._taken.emit(self.token, count)

    def thought(self, piece: str) -> None:
        self.model._thought.emit(self.token, piece)

    def usage(self, usage: Usage) -> None:
        self.model._usage.emit(self.token, usage)

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
    phase_changed = Signal(str)  # what the turn does now; "" once it ended
    usage_changed = Signal()  # the chat's tokens (usage, context_limit)

    # From the turn's thread, queued to the GUI thread: (turn, ...)
    _asking = Signal(object)
    _taken = Signal(object, int)
    _thought = Signal(object, str)
    _usage = Signal(object, object)
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
        self.usage = Tokens()  # of the chat
        self.phase = ""
        self._turn: Optional[object] = None
        self._began = 0.0  # when the turn began (time.monotonic)
        self._turn_usage = Tokens()
        self._answer: Optional[int] = None  # the item the model's words go to
        self._thinking: Optional[int] = None  # the thought the model thinks now
        self._calls: Dict[str, int] = {}  # call id -> its item
        self._queued: List[int] = []  # the person's items that wait, in order
        self._reach: Optional[Reach] = None
        self._reach_lock = threading.Lock()
        self._lab_changed = False  # the next turn reaches the lab anew
        self._asking.connect(self._heard_asking)
        self._taken.connect(self._heard_taken)
        self._thought.connect(self._heard_thought)
        self._usage.connect(self._heard_usage)
        self._text.connect(self._heard_text)
        self._called.connect(self._heard_call)
        self._progress.connect(self._heard_progress)
        self._answered.connect(self._heard_answer)
        self._ended.connect(self._heard_end)
        session.station_changed.connect(self._another_lab)
        session.config_changed.connect(self._bench_changed)
        providers.changed.connect(self.usage_changed)

    def busy(self) -> bool:
        return self._turn is not None

    def elapsed(self) -> float:
        """Seconds the turn has run; 0 without one."""
        return time.monotonic() - self._began if self.busy() else 0.0

    def context_limit(self) -> Optional[int]:
        """The tokens the chosen model takes, when known."""
        provider = self.providers.chosen()
        return provider.context if provider is not None else None

    def send(self, text: str, attachments: Sequence[Attachment] = ()) -> None:
        """The person's message: the model answers it with the bench's tools.
        While a turn runs it waits and joins at the turn's next step."""
        text = text.strip()
        if not text and not attachments:
            return
        message = content(text, attachments)
        index = self._add(
            Item(Kind.PERSON, text, attachments=tuple(attachments), queued=self.busy())
        )
        if self.busy():
            self._queued.append(index)
            self.conversation.queue(message)
            return
        self._begin(message)

    def _begin(self, message: Optional[Content]) -> None:
        """A turn: the model answers message, then what waits."""
        provider = self.providers.chosen()
        if provider is None:
            self._add(Item(Kind.NOTE, NO_PROVIDER))
            return
        client = Client(provider, self.providers.key(provider.name))
        conversation = self.conversation
        token = conversation.begin()
        self._turn, self._answer, self._thinking = token, None, None
        self._began, self._turn_usage = time.monotonic(), Tokens()
        self.busy_changed.emit(True)
        self._set_phase(THINKING)
        listener = _Turn(self, token)
        folder = self.session.workspace
        window = self.session.window  # what it shows goes to its own window

        def run() -> None:
            try:
                reach = self._reached()
            except LabError as e:
                conversation.stop()
                self._ended.emit(token, Outcome.FAILED.value, str(e))
                return
            outcome, why = conversation.say(
                token, message, client,
                tools(lambda: folder.folder, lambda: window), reach,
                system_prompt, listener,
            )  # fmt: skip
            self._ended.emit(token, outcome.value, why)

        threading.Thread(target=run, name="assistant", daemon=True).start()

    def stop(self) -> None:
        """End the turn now: its calls without an answer are stopped, what
        waited is not sent."""
        if self._turn is None:
            return
        self.conversation.stop()
        self._end(Outcome.STOPPED, "")

    def new_chat(self) -> None:
        """Forget the conversation (a turn running is stopped)."""
        self.stop()
        self.conversation = Conversation()
        self.items.clear()
        self.usage = Tokens()
        self.cleared.emit()
        self.usage_changed.emit()

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
    def _heard_asking(self, token: object) -> None:
        if token is self._turn:
            self._turn_usage.steps += 1
            self._set_phase(THINKING)

    def _heard_taken(self, token: object, count: int) -> None:
        if token is not self._turn:
            return
        taken, self._queued = self._queued[:count], self._queued[count:]
        for index in taken:
            self.items[index].queued = False
            self.item_changed.emit(index)
        self._answer = None  # the answer to it goes below it

    def _heard_thought(self, token: object, piece: str) -> None:
        if token is not self._turn:
            return
        if self._thinking is None:
            self._answer = None
            self._thinking = self._add(
                Item(Kind.THOUGHT, state=State.RUNNING, started=time.monotonic())
            )
        self.items[self._thinking].text += piece
        self.item_changed.emit(self._thinking)
        self._set_phase(THINKING)

    def _heard_usage(self, token: object, usage: Usage) -> None:
        if token is not self._turn:
            return
        self._turn_usage.add(usage)
        self.usage.add(usage)
        self.usage_changed.emit()

    def _heard_text(self, token: object, piece: str) -> None:
        if token is not self._turn:
            return
        self._thought_over(State.DONE)
        if self._answer is None:
            self._answer = self._add(Item(Kind.ANSWER))
        self.items[self._answer].text += piece
        self.item_changed.emit(self._answer)
        self._set_phase(WRITING)

    def _heard_call(self, token: object, call: ToolCall) -> None:
        if token is not self._turn:
            return
        self._thought_over(State.DONE)
        self._answer = None  # words after it go below it
        try:
            given = arguments(call)
        except LabError:  # the model reads why; the card shows none
            given = {}
        self._calls[call.id] = self._add(
            Item(Kind.CALL, name=call.name, arguments=given, state=State.RUNNING)
        )
        self._set_phase(f"{RUNNING} {call.name}")

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

    def _thought_over(self, state: State) -> None:
        if self._thinking is None:
            return
        item = self.items[self._thinking]
        item.state, item.seconds = state, time.monotonic() - item.started
        self.item_changed.emit(self._thinking)
        self._thinking = None

    def _end(self, outcome: Outcome, why: str) -> None:
        self._thought_over(State.STOPPED)
        for index in self._calls.values():
            self.items[index].state = State.STOPPED
            self.item_changed.emit(index)
        self._calls.clear()
        seconds = time.monotonic() - self._began
        self._turn = self._answer = None
        note = {
            Outcome.STOPPED: "Stopped.",
            Outcome.STEPS: f"Stopped after {MAX_STEPS} steps: say “go on” to continue.",
            Outcome.FAILED: why,
        }.get(outcome)
        if note:
            self._add(Item(Kind.NOTE, note))
        steps = self._turn_usage.steps
        told = [f"{seconds:.1f} s", f"{steps} step{'s' if steps != 1 else ''}"]
        used = self._turn_usage.told()
        self._add(Item(Kind.STATS, " · ".join(told + ([used] if used else []))))
        if outcome is Outcome.ANSWERED and self._queued:
            self._begin(None)  # written as it answered: it answers that too
            if self.busy():
                return
        if self._queued:  # stopped or failed: what waited does not go
            self.conversation.stop()
            for index in self._queued:
                self.items[index].queued, self.items[index].unsent = False, True
                self.item_changed.emit(index)
            self._queued.clear()
        self._set_phase("")
        self.busy_changed.emit(False)

    def _set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
            self.phase_changed.emit(phase)

    def _add(self, item: Item) -> int:
        self.items.append(item)
        self.added.emit(len(self.items) - 1)
        return len(self.items) - 1
