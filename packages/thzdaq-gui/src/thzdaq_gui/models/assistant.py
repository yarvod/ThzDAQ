"""The assistant of the window: its model servers (ProvidersModel), the
person's instructions to it (InstructionsModel) and its chat (AssistantModel),
on QtCore.

The chat has modes, each a chat backend of its own (assistant/chat.py, Chat:
the built-in assistant, built_in_chat()) with its own items, tokens and turn
(Mode); the dock shows one of them. The model knows a backend only through
that interface.

A turn runs in a thread of its own (it waits for the model, for the bench,
for the person's consent); what it tells waits in one queue that the GUI
thread takes whole, woken by a queued signal when the queue was empty. The
model owns the items: however many pieces came meanwhile, each item changed
is told once per take, so a model that writes faster than the window draws
never piles work up for it. Stop ends the turn at once: what is still on its
way from the stopped turn is dropped.

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
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance

from thzdaq_gui.assistant.attachments import Attachment
from thzdaq_gui.assistant.builtin import BuiltInChat
from thzdaq_gui.assistant.chat import (
    Call,
    Chat,
    Choice,
    Outcome,
    Said,
    Unready,
    Used,
)
from thzdaq_gui.assistant.keys import Keys
from thzdaq_gui.assistant.provider import Client, Provider, ProviderError
from thzdaq_gui.settings import (
    ASSISTANT_INSTRUCTIONS,
    ASSISTANT_PROVIDER,
    ASSISTANT_PROVIDERS,
    settings,
)

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


class InstructionsModel(QObject):
    """The person's instructions to the assistant: one text in the program's
    settings, the same in every workspace. They add to the built-in prompt
    (prompt.system_prompt), they never replace its rules."""

    changed = Signal()

    def instructions(self) -> str:
        """As the person wrote them; empty: none."""
        return settings().value(ASSISTANT_INSTRUCTIONS) or ""

    def set_instructions(self, text: str) -> None:
        if text == self.instructions():
            return
        settings().setValue(ASSISTANT_INSTRUCTIONS, text)
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
    """Tokens summed over steps; context: how much of the model's context the
    conversation fills, as last told."""

    read: int = 0
    written: int = 0
    reasoning: int = 0
    steps: int = 0
    context: int = 0

    def add(self, used: Used) -> None:
        self.read += used.read
        self.written += used.written
        self.reasoning += used.reasoning
        if used.context is not None:
            self.context = used.context

    def known(self) -> bool:
        """Whether the tokens read and written were told."""
        return bool(self.read or self.written)

    def told(self) -> str:
        """In a line: "4.2k in · 310 out (120 thinking)"."""
        if not self.known():
            return ""
        thinking = f" ({tokens(self.reasoning)} thinking)" if self.reasoning else ""
        return f"{tokens(self.read)} in · {tokens(self.written)} out{thinking}"


def built_in_chat(
    session, providers: ProvidersModel, instructions: InstructionsModel
) -> BuiltInChat:
    """The built-in assistant, a mode of the chat: its models are the servers
    of the settings, told when they change."""
    chat = BuiltInChat(session, providers, instructions)
    providers.changed.connect(chat.servers_changed)
    return chat


class _Turn:
    """A turn of a mode, the listener its chat tells (chat.Listener): what it
    tells goes into the model's queue, heard while this is the mode's turn and
    never once it was stopped."""

    def __init__(self, model: "AssistantModel", mode: "Mode"):
        self.model, self.mode = model, mode

    def heard(self) -> bool:
        return self.mode.turn is self

    def asking(self) -> None:
        self.model._tell(self, self.mode._heard_asking)

    def taken(self, count: int) -> None:
        self.model._tell(self, self.mode._heard_taken, count)

    def thought(self, piece: str) -> None:
        self.model._tell(self, self.mode._heard_thought, piece)

    def text(self, piece: str) -> None:
        self.model._tell(self, self.mode._heard_text, piece)

    def called(self, call: Call) -> None:
        self.model._tell(self, self.mode._heard_call, call)

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        self.model._tell(self, self.mode._heard_progress, call, (done, total))

    def answered(self, call: str, text: str, failed: bool) -> None:
        self.model._tell(self, self.mode._heard_answer, call, text, failed)

    def usage(self, used: Used) -> None:
        self.model._tell(self, self.mode._heard_usage, used)

    def ended(self, outcome: Outcome, why: str) -> None:
        self.model._tell(self, self.mode._end, outcome, why)


class _Watch:
    """What a mode's chat tells apart from its turns, from any thread: its
    models changed. Always heard."""

    def __init__(self, model: "AssistantModel", mode: "Mode"):
        self.model, self.mode = model, mode

    def heard(self) -> bool:
        return True

    def __call__(self) -> None:
        self.model._tell(self, self.model._models_changed, self.mode)


class Mode:
    """A chat of the dock: its backend (Chat), its items, its tokens and the
    turn it runs. What its turns tell comes through the model's queue; what
    changed it tells the model, which tells the dock while this is the mode
    shown (a mode chosen is shown anew, whole)."""

    def __init__(self, model: "AssistantModel", chat: Chat):
        self.model = model
        self.chat = chat
        self.title = chat.title
        self.items: List[Item] = []
        self.usage = Tokens()  # of the chat
        self.last = Tokens()  # of the last turn, or of the one running
        self.phase = ""
        self.turn: Optional[_Turn] = None
        self._began = 0.0  # when the turn began (time.monotonic)
        self._answer: Optional[int] = None  # the item the model's words go to
        self._thinking: Optional[int] = None  # the thought the model thinks now
        self._calls: Dict[str, int] = {}  # call id -> its item
        self._queued: List[int] = []  # the person's items that wait, in order
        chat.watch(_Watch(model, self))

    def busy(self) -> bool:
        return self.turn is not None

    def elapsed(self) -> float:
        """Seconds the turn has run; 0 without one."""
        return time.monotonic() - self._began if self.busy() else 0.0

    def thinking(self) -> Optional[int]:
        """The item of the thought the model thinks now; None without one."""
        return self._thinking

    def send(self, text: str, attachments: Sequence[Attachment]) -> None:
        text = text.strip()
        if not text and not attachments:
            return
        said = Said(text, tuple(attachments))
        index = self._add(
            Item(Kind.PERSON, text, attachments=said.attachments, queued=self.busy())
        )
        if self.busy():
            self._queued.append(index)
            self.chat.queue(said)
            return
        self._begin(said)

    def _begin(self, said: Optional[Said]) -> None:
        """A turn: the model answers said, then what waits. What the chat
        tells as it starts is taken after this (the queue's signal is
        queued)."""
        turn = _Turn(self.model, self)
        try:
            self.chat.start(said, turn)
        except Unready as e:
            self._add(Item(Kind.NOTE, str(e)))
            return
        self.turn, self._answer, self._thinking = turn, None, None
        self._began, self.last = time.monotonic(), Tokens()
        self.model._emit_shown(self, self.model.busy_changed, True)
        self._set_phase(THINKING)

    def stop(self) -> None:
        if self.turn is None:
            return
        self.chat.stop()
        self._end(Outcome.STOPPED, "")
        self.model._show_changes()

    def new_chat(self) -> None:
        self.stop()
        self.chat.new_chat()
        self.items.clear()
        self.usage, self.last = Tokens(), Tokens()
        self.model._emit_shown(self, self.model.cleared)
        self.model._emit_shown(self, self.model.usage_changed)

    def close(self) -> None:
        self.stop()
        self.chat.close()

    # What its turn told, in the GUI thread
    def _heard_asking(self) -> None:
        self.last.steps += 1
        self.usage.steps += 1
        self._set_phase(THINKING)

    def _heard_taken(self, count: int) -> None:
        taken, self._queued = self._queued[:count], self._queued[count:]
        for index in taken:
            self.items[index].queued = False
            self._change(index)
        self._answer = None  # the answer to it goes below it

    def _heard_thought(self, piece: str) -> None:
        if self._thinking is None:
            self._answer = None
            self._thinking = self._add(
                Item(Kind.THOUGHT, state=State.RUNNING, started=time.monotonic())
            )
        self.items[self._thinking].text += piece
        self._change(self._thinking)
        self._set_phase(THINKING)

    def _heard_usage(self, used: Used) -> None:
        self.last.add(used)
        self.usage.add(used)
        self.model._emit_shown(self, self.model.usage_changed)

    def _heard_text(self, piece: str) -> None:
        self._thought_over(State.DONE)
        if self._answer is None:
            self._answer = self._add(Item(Kind.ANSWER))
        self.items[self._answer].text += piece
        self._change(self._answer)
        self._set_phase(WRITING)

    def _heard_call(self, call: Call) -> None:
        self._thought_over(State.DONE)
        self._answer = None  # words after it go below it
        self._calls[call.id] = self._add(
            Item(
                Kind.CALL,
                name=call.name,
                arguments=dict(call.arguments),
                state=State.RUNNING,
            )
        )
        self._set_phase(f"{RUNNING} {call.name}")

    def _heard_progress(self, call: str, progress) -> None:
        if call in self._calls:
            self.items[self._calls[call]].progress = progress
            self._change(self._calls[call])

    def _heard_answer(self, call: str, text: str, failed: bool) -> None:
        if call not in self._calls:
            return
        index = self._calls.pop(call)
        item = self.items[index]
        item.text, item.state = text, State.REFUSED if failed else State.DONE
        self._change(index)

    def _thought_over(self, state: State) -> None:
        if self._thinking is None:
            return
        item = self.items[self._thinking]
        item.state, item.seconds = state, time.monotonic() - item.started
        self._change(self._thinking)
        self._thinking = None

    def _end(self, outcome: Outcome, why: str) -> None:
        """The turn ended (told by it, or stopped here); its items changed
        are told by whoever called."""
        self._thought_over(State.STOPPED)
        for index in self._calls.values():
            self.items[index].state = State.STOPPED
            self._change(index)
        self._calls.clear()
        seconds = time.monotonic() - self._began
        self.turn = self._answer = None
        steps = self.last.steps
        note = {
            Outcome.STOPPED: "Stopped.",
            Outcome.STEPS: f"Stopped after {steps} steps: say “go on” to continue.",
            Outcome.FAILED: why,
        }.get(outcome)
        if note:
            self._add(Item(Kind.NOTE, note))
        told = [f"{seconds:.1f} s", f"{steps} step{'s' if steps != 1 else ''}"]
        used = self.last.told()
        self._add(Item(Kind.STATS, " · ".join(told + ([used] if used else []))))
        if outcome is Outcome.ANSWERED and self._queued:
            self._begin(None)  # written as it answered: it answers that too
            if self.busy():
                return
        if self._queued:  # stopped or failed: what waited does not go
            self.chat.stop()
            for index in self._queued:
                self.items[index].queued, self.items[index].unsent = False, True
                self._change(index)
            self._queued.clear()
        self._set_phase("")
        self.model._emit_shown(self, self.model.busy_changed, False)

    def _set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
            self.model._emit_shown(self, self.model.phase_changed, phase)

    def _change(self, index: int) -> None:
        self.model._change(self, index)

    def _add(self, item: Item) -> int:
        self.items.append(item)
        self.model._emit_shown(self, self.model.added, len(self.items) - 1)
        return len(self.items) - 1


class AssistantModel(QObject):
    """The chat of the dock: a mode per chat given (the first shown), and
    what the mode shown has and does."""

    added = Signal(int)  # an item, at its index
    item_changed = Signal(int)
    cleared = Signal()
    busy_changed = Signal(bool)
    phase_changed = Signal(str)  # what the turn does now; "" once it ended
    usage_changed = Signal()  # the tokens (usage, last_usage, context_limit)
    models_changed = Signal()  # the models offered, the one chosen
    mode_changed = Signal()  # another mode shown: all of it anew

    # Turns told something, from their threads or this one: the queue was empty
    _arrived = Signal()

    def __init__(
        self,
        session,
        providers: ProvidersModel,
        instructions: InstructionsModel,
        chats: Sequence[Chat],
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        # The settings: the built-in chat's servers, the person's instructions
        self.providers = providers
        self.instructions = instructions
        # What turns told, waiting for the GUI thread: (whose, handler, args)
        self._told: List[Tuple[Any, Callable[..., None], tuple]] = []
        self._told_lock = threading.Lock()
        self._changed: Set[int] = set()  # items changed, told at the end of a take
        # Queued from the GUI thread too: what a chat tells as it starts a
        # turn is heard once that turn is the mode's
        self._arrived.connect(self._take_told, Qt.QueuedConnection)
        self.modes = [Mode(self, chat) for chat in chats]
        self.mode = self.modes[0]  # the one shown
        session.station_changed.connect(self._another_lab)
        session.config_changed.connect(self._prompt_changed)
        instructions.changed.connect(self._prompt_changed)

    # The mode shown
    @property
    def items(self) -> List[Item]:
        return self.mode.items

    @property
    def usage(self) -> Tokens:
        """Of the chat."""
        return self.mode.usage

    @property
    def last_usage(self) -> Tokens:
        """Of the last turn, or of the one running."""
        return self.mode.last

    @property
    def phase(self) -> str:
        return self.mode.phase

    def busy(self) -> bool:
        return self.mode.busy()

    def elapsed(self) -> float:
        return self.mode.elapsed()

    def thinking(self) -> Optional[int]:
        return self.mode.thinking()

    def context_limit(self) -> Optional[int]:
        """The tokens the chosen model takes, when known."""
        return self.mode.chat.context_limit()

    def models(self) -> Sequence[Choice]:
        return self.mode.chat.models()

    def chosen_model(self) -> Optional[str]:
        return self.mode.chat.model()

    def choose_model(self, model: str) -> None:
        self.mode.chat.choose(model)

    def send(self, text: str, attachments: Sequence[Attachment] = ()) -> None:
        """The person's message: the model answers it. While a turn runs it
        waits and joins at the turn's next step."""
        self.mode.send(text, attachments)

    def stop(self) -> None:
        """End the turn now: its calls without an answer are stopped, what
        waited is not sent."""
        self.mode.stop()

    def new_chat(self) -> None:
        """Forget the conversation (a turn running is stopped)."""
        self.mode.new_chat()

    def show_mode(self, index: int) -> None:
        """Show another mode; a turn it or the one shown before runs goes on."""
        mode = self.modes[index]
        if mode is self.mode:
            return
        self.mode = mode
        self._changed.clear()  # of the mode shown before
        self.mode_changed.emit()

    def close(self) -> None:
        """The window closes: the turns stop, the chats leave the daemon."""
        for mode in self.modes:
            mode.close()

    def _another_lab(self) -> None:
        for mode in self.modes:
            mode.chat.lab_changed()

    def _prompt_changed(self) -> None:
        """The bench or the person's instructions changed: the next turn makes
        the system prompt anew (a turn running keeps its own)."""
        for mode in self.modes:
            mode.chat.prompt_changed()

    def _models_changed(self, mode: Mode) -> None:
        self._emit_shown(mode, self.models_changed)
        self._emit_shown(mode, self.usage_changed)  # its context limit too

    # What turns told: queued in their threads, taken in the GUI thread
    def _tell(self, whose, heard: Callable[..., None], *told: Any) -> None:
        with self._told_lock:
            woken = not self._told  # an empty queue: nobody takes it yet
            self._told.append((whose, heard, told))
        if woken:
            self._arrived.emit()

    def _take_told(self) -> None:
        """All that waits, then each item changed told once."""
        with self._told_lock:
            told, self._told = self._told, []
        for whose, heard, given in told:
            if whose.heard():  # asked each time: an end may begin a turn
                heard(*given)
        self._show_changes()

    def _change(self, mode: Mode, index: int) -> None:
        if mode is self.mode:
            self._changed.add(index)

    def _show_changes(self) -> None:
        changed, self._changed = sorted(self._changed), set()
        for index in changed:
            self.item_changed.emit(index)

    def _emit_shown(self, mode: Mode, signal: SignalInstance, *told: Any) -> None:
        """A mode's signal, told while it is the mode shown."""
        if mode is self.mode:
            signal.emit(*told)
