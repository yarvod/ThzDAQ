"""The assistant of the window: its model servers (ProvidersModel), the
person's instructions to it (InstructionsModel), Codex's settings
(CodexSettingsModel) and its chat (AssistantModel), on QtCore.

The chat has modes, each a chat backend of its own (assistant/chat.py, Chat:
the built-in assistant, built_in_chat(); Codex, codex_chat()) with its own
items, tokens and turn (Mode); the dock shows one of them. The model knows a
backend only through that interface.

A turn runs in a thread of its own (it waits for the model, for the bench,
for the person's consent); what it tells waits in one queue that the GUI
thread takes whole, woken by a queued signal when the queue was empty. The
model owns the items: however many pieces came meanwhile, each item changed
is told once per take, so a model that writes faster than the window draws
never piles work up for it. Stop ends the turn at once: what is still on its
way from the stopped turn is dropped.

What the person sends while a turn runs waits and joins at the turn's next
step (queued, then sent; Codex takes it as its next turn). An agent that
acts on its own asks the person first (Codex runs a command, writes a file):
a card with its options, answered by the person, or cancelled once the turn
ends. The model tells what the turn does now (phase:
thinking, writing, running a tool), how long it runs, what the model thought
(a card that folds), and the tokens (Tokens): of each turn and of the chat,
what the model read (summed over its steps, each of which reads the whole
conversation again: what the server bills, not the context) and of it what
was cached, what it wrote and of it what it thought; and, apart, how much of
the model's context the conversation fills (the last step's). An image the
assistant shows is an item of its own, an answer alone or among words.

The mode shown offers its chat's models, the chosen model's reasoning
efforts, and what its agent may do without asking (policies: Codex's modes),
each chosen through the chat; shown in the dock it gets ready (prepare: Codex
starts its adapter and a session in the background, so its models are known
before the first message).

A mode's chat keeps its conversations (Chat.chats, open, rename): the
model lists those of the window's workspace as the mode is first shown and
again as History opens (history, searched by title; while they are being
found, finding_chats, those found so far: Codex's come page by page), opens
one in place of the one shown (a turn running is stopped first) and renames
one. An opened conversation comes back as its
chat tells it again (chat.Replay), gathered in the chat's thread and handed
to the GUI thread whole through the same queue: one take, the items made by
the handlers that make a live turn's. What the person sends meanwhile waits
for it. The measurements a conversation started go on in the daemon.
"""

import json
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance

from thzdaq_gui.assistant import codex
from thzdaq_gui.assistant.acp import Options, choice, setting
from thzdaq_gui.assistant.attachments import Attachment
from thzdaq_gui.assistant.builtin import BuiltInChat
from thzdaq_gui.assistant.chat import (
    Asked,
    Call,
    Chat,
    Choice,
    Image,
    Kept,
    Limit,
    Offered,
    Outcome,
    Said,
    Unready,
    Used,
)
from thzdaq_gui.assistant.codex import CodexChat
from thzdaq_gui.assistant.history import Shelf
from thzdaq_gui.assistant.keys import Keys
from thzdaq_gui.assistant.provider import Client, Provider, ProviderError
from thzdaq_gui.settings import (
    ASSISTANT_INSTRUCTIONS,
    ASSISTANT_PROVIDER,
    ASSISTANT_PROVIDERS,
    CODEX_COMMAND,
    CODEX_EXECUTABLE,
    CODEX_KNOWN,
    CODEX_MODE,
    CODEX_OPTIONS,
    chats_dir,
    settings,
)

SHOWN = 40  # letters of an argument a card's line shows
# What a turn does now
THINKING, WRITING, RUNNING = "Thinking", "Writing", "Running"
ASKING = "Waiting for your answer"
THOUGHT = "Thought"  # a thought over, how long not known
CACHED, REASONING = "cached", "reasoning"  # of the tokens read, of those written


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


class CodexSettingsModel(QObject):
    """Codex's settings, in the program's settings: the adapter's command
    line, the codex it runs (empty: its own), the mode a new chat starts in,
    and what the person chose of a session's options last (codex.Settings).
    Test starts the adapter and initializes it only."""

    tested = Signal(bool, str)  # it works, what was found or what is wrong

    def command(self) -> str:
        return settings().value(CODEX_COMMAND) or codex.COMMAND

    def executable(self) -> str:
        return settings().value(CODEX_EXECUTABLE) or ""

    def mode(self) -> str:
        return settings().value(CODEX_MODE) or codex.WORKSPACE_WRITE

    def chosen(self) -> Tuple[str, ...]:
        kept = settings().value(CODEX_OPTIONS)
        return tuple(choice(*pair) for pair in json.loads(kept).items()) if kept else ()

    def choose(self, made: str) -> None:
        kept = settings().value(CODEX_OPTIONS)
        chosen = json.loads(kept) if kept else {}
        option, value = setting(made)
        chosen.pop(option, None)  # in the order chosen: a model before its effort
        chosen[option] = value
        settings().setValue(CODEX_OPTIONS, json.dumps(chosen))

    def known(self) -> Optional[Options]:
        """Options kept by a version that kept them otherwise are none."""
        kept = settings().value(CODEX_KNOWN)
        try:
            return Options.restored(json.loads(kept)) if kept else None
        except (ValueError, TypeError, AttributeError):  # not of the shape saved
            return None

    def keep(self, options: Options) -> None:
        settings().setValue(CODEX_KNOWN, json.dumps(options.saved()))

    def save(self, command: str, executable: str, mode: str) -> None:
        """What the page holds; a new chat starts with it."""
        kept = settings()
        kept.setValue(CODEX_COMMAND, command.strip() or codex.COMMAND)
        kept.setValue(CODEX_EXECUTABLE, executable.strip())
        kept.setValue(CODEX_MODE, mode)

    def test(self, command: str, executable: str) -> None:
        """Whether the adapter of this command starts and is one that works:
        told by tested, from a thread of its own."""
        given = _Given(command.strip() or codex.COMMAND, executable.strip())
        codex.test(given, self.tested.emit)


@dataclass(frozen=True)
class _Given:
    """The adapter as the settings page holds it, before it is saved."""

    line: str
    path: str

    def command(self) -> str:
        return self.line

    def executable(self) -> str:
        return self.path


class Kind(str, Enum):
    PERSON = "person"  # what the person wrote
    ANSWER = "answer"  # what the model answered
    THOUGHT = "thought"  # what the model thought before: a card
    CALL = "call"  # a tool call: a card
    NOTE = "note"  # how a turn ended when it did not answer
    STATS = "stats"  # how long a turn took and its tokens
    PERMISSION = "permission"  # what an agent asks before it acts: a card
    IMAGE = "image"  # an image the assistant shows


class State(str, Enum):
    """Of a tool call, of a thought, or of what an agent asks."""

    RUNNING = "running"  # a question: waits for the person
    DONE = "done"  # a question: answered
    REFUSED = "refused"  # refused or wrong: the model reads why
    STOPPED = "stopped"  # a question: its turn ended first


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
    # Of a thought: when it began, of one thought as the chat runs
    # (time.monotonic); how long it took, once over, when known
    started: Optional[float] = None
    seconds: Optional[float] = None
    # Of what an agent asks: the question, the id of the option chosen
    asked: Optional[Asked] = None
    chosen: Optional[str] = None
    image: Optional[Image] = None  # of an image shown

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
        if self.state is State.RUNNING:
            since = self.started
            return f"{THINKING}…" + (
                "" if since is None else f" {time.monotonic() - since:.0f} s"
            )
        if self.seconds is None:
            return THOUGHT
        return f"{THOUGHT} for {self.seconds:.0f} s"


def _shown(value: Any) -> str:
    """An argument in the card's line: a long one (a script's text) cut."""
    if isinstance(value, dict):
        return " ".join(f"{k}={_shown(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ",".join(_shown(v) for v in value)
    text = " ".join(str(value).split())
    return text if len(text) <= SHOWN else text[: SHOWN - 1] + "…"


def ago(when: float, now: float) -> str:
    """How long ago, in words (seconds since the epoch): "5 min ago"."""
    seconds = max(now - when, 0)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60:.0f} min ago"
    if seconds < 86400:
        return f"{seconds // 3600:.0f} h ago"
    if seconds < 2 * 86400:
        return "yesterday"
    if seconds < 7 * 86400:
        return f"{seconds // 86400:.0f} days ago"
    year = "" if time.localtime(when).tm_year == time.localtime(now).tm_year else " %Y"
    return time.strftime(f"%d %b{year}", time.localtime(when))


def matching(chats: Sequence[Kept], search: str) -> List[Kept]:
    """The chats whose title holds what is searched, whatever the case."""
    found = search.strip().casefold()
    return [chat for chat in chats if found in chat.title.casefold()]


def tokens(count: int) -> str:
    """1234 -> 1.2k"""
    if count < 1000:
        return str(count)
    return f"{count / 1000:.1f}k" if count < 100_000 else f"{count // 1000}k"


@dataclass
class Tokens:
    """Tokens of a turn or of a chat, summed over the model's steps (an
    agent's requests): read, all the input it read, each step the whole
    conversation again, so what the server bills and more than the context;
    of it cached, what came from the server's cache (None: never told);
    written, all it wrote, of it reasoning, what it thought. Context: how much
    of the model's context the conversation fills, as last told."""

    read: int = 0
    written: int = 0
    reasoning: int = 0
    steps: int = 0
    context: int = 0
    cached: Optional[int] = None

    def add(self, used: Used) -> None:
        self.read += used.read
        self.written += used.written
        self.reasoning += used.reasoning
        if used.cached is not None:
            self.cached = (self.cached or 0) + used.cached
        if used.context is not None:
            self.context = used.context

    def known(self) -> bool:
        """Whether the tokens read and written were told."""
        return bool(self.read or self.written)

    def told(self) -> str:
        """In a line, as the turn's stats and the popup's "In" and "Out" say
        them: "4.2k in (3.9k cached) · 310 out (120 reasoning)"."""
        if not self.known():
            return ""
        cached = f" ({tokens(self.cached)} {CACHED})" if self.cached else ""
        thought = f" ({tokens(self.reasoning)} {REASONING})" if self.reasoning else ""
        return f"{tokens(self.read)} in{cached} · {tokens(self.written)} out{thought}"


def share(used: int, limit: Optional[int]) -> Optional[float]:
    """How much of the context is filled (0…1); None while the limit is not
    known."""
    return min(used / limit, 1.0) if limit else None


def codex_chat(
    session, codex_settings: CodexSettingsModel, instructions: InstructionsModel
) -> CodexChat:
    """Codex, a mode of the chat, over ACP: with the person's instructions as
    its system prompt, in the settings' mode."""
    return CodexChat(session, codex_settings, instructions)


def built_in_chat(
    session, providers: ProvidersModel, instructions: InstructionsModel
) -> BuiltInChat:
    """The built-in assistant, a mode of the chat: its models are the servers
    of the settings, told when they change; its conversations are kept in the
    program's data."""
    chat = BuiltInChat(session, providers, instructions, Shelf(chats_dir()))
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

    def image(self, image: Image) -> None:
        self.model._tell(self, self.mode._heard_image, image)

    def usage(self, used: Used) -> None:
        self.model._tell(self, self.mode._heard_usage, used)

    def ended(self, outcome: Outcome, why: str) -> None:
        self.model._tell(self, self.mode._end, outcome, why)

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        self.model._tell(self, self.mode._heard_permission, asked, answer)


class _Watch:
    """What a mode's chat tells apart from its turns, from any thread: its
    models changed. Always heard."""

    def __init__(self, model: "AssistantModel", mode: "Mode"):
        self.model, self.mode = model, mode

    def heard(self) -> bool:
        return True

    def __call__(self) -> None:
        self.model._tell(self, self.model._models_changed, self.mode)


class _Opening:
    """A kept conversation as its chat tells it again (chat.Replay): what it
    tells is gathered in the chat's thread and handed to the GUI thread whole
    once all of it was told, heard while this is the mode's opening. What the
    person sends meanwhile waits here."""

    def __init__(self, model: "AssistantModel", mode: "Mode"):
        self.model, self.mode = model, mode
        self.told: List[Tuple[Callable[..., None], tuple]] = []  # chat's thread
        self.held: List[Tuple[str, Tuple[Attachment, ...]]] = []  # GUI thread

    def heard(self) -> bool:
        return self.mode.opening is self

    def began(self, said: Optional[Said]) -> None:
        self.told.append((self.mode._replayed_began, (said,)))

    def said(self, said: Said) -> None:
        self.told.append((self.mode._replayed_said, (said,)))

    def asking(self) -> None:
        self.told.append((self.mode._heard_asking, ()))

    def taken(self, count: int) -> None:
        self.told.append((self.mode._heard_taken, (count,)))

    def thought(self, piece: str, seconds: Optional[float] = None) -> None:
        self.told.append((self.mode._heard_thought, (piece, seconds)))

    def text(self, piece: str) -> None:
        self.told.append((self.mode._heard_text, (piece,)))

    def called(self, call: Call) -> None:
        self.told.append((self.mode._heard_call, (call,)))

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        self.told.append((self.mode._heard_progress, (call, (done, total))))

    def answered(self, call: str, text: str, failed: bool) -> None:
        self.told.append((self.mode._heard_answer, (call, text, failed)))

    def image(self, image: Image) -> None:
        self.told.append((self.mode._heard_image, (image,)))

    def usage(self, used: Used) -> None:
        self.told.append((self.mode._heard_usage, (used,)))

    def ended(
        self, outcome: Outcome, why: str, seconds: Optional[float] = None
    ) -> None:
        self.told.append((self.mode._replayed_end, (outcome, why, seconds)))

    def opened(self, why: str = "") -> None:
        self.model._tell(self, self.mode._opened, self, why)

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        """Nothing is asked of a conversation told again."""
        answer(None)


class _Listing:
    """The kept conversations a mode's chat found, from its thread: heard
    while this is the mode's last listing."""

    def __init__(self, model: "AssistantModel", mode: "Mode"):
        self.model, self.mode = model, mode

    def heard(self) -> bool:
        return self.mode.listing is self

    def __call__(self, chats: Sequence[Kept], whole: bool) -> None:
        self.model._tell(self, self.mode._found, tuple(chats), whole)


class Mode:
    """A chat of the dock: its backend (Chat), its items, its tokens and the
    turn it runs; the conversations it keeps (history) and the one it opens.
    What its turns tell comes through the model's queue; what changed it
    tells the model, which tells the dock while this is the mode shown (a
    mode chosen is shown anew, whole)."""

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
        self._asked: Dict[int, Callable[[Optional[str]], None]] = {}  # item -> answer
        self._queued: List[int] = []  # the person's items that wait, in order
        self.history: Tuple[Kept, ...] = ()  # of the workspace, as listed last
        self.listing: Optional[_Listing] = None  # asked last
        self.finding_chats = False  # the last listing is not whole yet
        self.opening: Optional[_Opening] = None  # a kept one being told again
        self._warmed = False
        # What its chat offers as last read in the GUI thread: its chat may
        # change it in a thread of its own, the window learns it with its signal
        self.offered: Offered = chat.offered()
        chat.watch(_Watch(model, self))

    def prepare(self, workspace) -> None:
        """Shown: its chat gets ready in the background and its conversations
        of the workspace are listed, the first time."""
        if not self._warmed:
            self._warmed = True
            self.chat.warm()
            self.find_chats(workspace)

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
        if self.opening is not None:  # it goes once the chat opened
            self.opening.held.append((text, tuple(attachments)))
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
        self.opening = None
        self.chat.new_chat()
        self._clear()

    def current(self) -> Optional[str]:
        """The id of the conversation shown; None before its first message."""
        kept = self.chat.current()
        return kept.id if kept is not None else None

    def find_chats(self, workspace) -> None:
        """List the conversations kept for the workspace (history, told by
        history_changed once found)."""
        self.listing = _Listing(self.model, self)
        self.finding_chats = True
        self.model._emit_shown(self, self.model.history_changed)
        self.chat.chats(workspace, self.listing)

    def open(self, chat: Kept) -> None:
        """Show a kept conversation and go on with it; a turn running is
        stopped first, what is sent meanwhile goes once it opened."""
        if self.opening is None and self.current() == chat.id:
            return  # shown already
        held = self.opening.held if self.opening is not None else []
        self.stop()
        self.opening = _Opening(self.model, self)
        self.opening.held = held
        self.chat.open(chat, self.opening)
        self._clear()

    def rename(self, chat: Kept, title: str) -> None:
        title = " ".join(title.split())
        if not title or title == chat.title:
            return
        self.chat.rename(chat, title)
        self.history = tuple(
            replace(kept, title=title) if kept.id == chat.id else kept
            for kept in self.history
        )
        self.model._emit_shown(self, self.model.history_changed)

    def _clear(self) -> None:
        self.items.clear()
        self._queued.clear()
        self.usage, self.last = Tokens(), Tokens()
        self.model._emit_shown(self, self.model.cleared)
        self.model._emit_shown(self, self.model.usage_changed)

    def _found(self, chats: Tuple[Kept, ...], whole: bool) -> None:
        """Those found so far join those listed before until all are found:
        a list listed anew never shrinks to its first page meanwhile."""
        if not whole:
            ids = {chat.id for chat in chats}
            chats += tuple(kept for kept in self.history if kept.id not in ids)
            chats = tuple(sorted(chats, key=lambda chat: chat.updated, reverse=True))
        self.history, self.finding_chats = chats, not whole
        self.model._emit_shown(self, self.model.history_changed)

    def close(self) -> None:
        self.stop()
        self.chat.close()

    # What its turn told, in the GUI thread
    def _heard_asking(self) -> None:
        self.last.steps += 1
        self.usage.steps += 1
        self._doing(THINKING)

    def _heard_taken(self, count: int) -> None:
        taken, self._queued = self._queued[:count], self._queued[count:]
        for index in taken:
            self.items[index].queued = False
            self._change(index)
        self._answer = None  # the answer to it goes below it

    def _heard_thought(self, piece: str, seconds: Optional[float] = None) -> None:
        """seconds: how long the whole thought took, of one told again."""
        if self._thinking is None:
            self._answer = None
            began = time.monotonic() if self.turn is not None else None
            self._thinking = self._add(
                Item(Kind.THOUGHT, state=State.RUNNING, started=began)
            )
        item = self.items[self._thinking]
        item.text += piece
        if seconds is not None:
            item.seconds = seconds
        self._change(self._thinking)
        self._doing(THINKING)

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
        self._doing(WRITING)

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
        self._doing(f"{RUNNING} {call.name}")

    def _heard_progress(self, call: str, progress) -> None:
        if call in self._calls:
            self.items[self._calls[call]].progress = progress
            self._change(self._calls[call])

    def _heard_permission(
        self, asked: Asked, answer: Callable[[Optional[str]], None]
    ) -> None:
        self._thought_over(State.DONE)
        self._answer = None  # words after it go below it
        index = self._add(
            Item(Kind.PERMISSION, asked.title, state=State.RUNNING, asked=asked)
        )
        self._asked[index] = answer
        self._doing(ASKING)

    def answer(self, index: int, option: str) -> None:
        """The person's answer to what the agent asks (an option's id); once."""
        answer = self._asked.pop(index, None)
        if answer is None:
            return
        item = self.items[index]
        item.state, item.chosen = State.DONE, option
        self._change(index)
        answer(option)
        self._doing(RUNNING)

    def _heard_answer(self, call: str, text: str, failed: bool) -> None:
        if call not in self._calls:
            return
        index = self._calls.pop(call)
        item = self.items[index]
        item.text, item.state = text, State.REFUSED if failed else State.DONE
        self._change(index)

    def _heard_image(self, image: Image) -> None:
        self._thought_over(State.DONE)
        self._answer = None  # words after it go below it
        self._add(Item(Kind.IMAGE, image.name, image=image))

    def _thought_over(self, state: State) -> None:
        if self._thinking is None:
            return
        item = self.items[self._thinking]
        item.state = state
        if item.seconds is None and item.started is not None:
            item.seconds = time.monotonic() - item.started
        self._change(self._thinking)
        self._thinking = None

    def _end(self, outcome: Outcome, why: str) -> None:
        """The turn ended (told by it, or stopped here); its items changed
        are told by whoever called."""
        self.turn = None
        self._close(outcome, why, time.monotonic() - self._began)
        if outcome is Outcome.ANSWERED and self._queued:
            self._begin(None)  # written as it answered: it answers that too
            if self.busy():
                return
        if self._queued:  # stopped or failed: what waited does not go
            self.chat.stop()
            self._unsent()
        self._set_phase("")
        self.model._emit_shown(self, self.model.busy_changed, False)

    def _close(self, outcome: Outcome, why: str, seconds: Optional[float]) -> None:
        """The items of a turn over: its thought and calls ended, a note when
        it did not answer, how long it took (when known) and its tokens."""
        self._thought_over(State.STOPPED)
        for index in self._calls.values():
            self.items[index].state = State.STOPPED
            self._change(index)
        self._calls.clear()
        for index, answer in self._asked.items():  # not answered: cancelled
            self.items[index].state = State.STOPPED
            self._change(index)
            answer(None)
        self._asked.clear()
        self._answer = None
        steps = self.last.steps
        note = {
            Outcome.STOPPED: "Stopped.",
            Outcome.STEPS: f"Stopped after {steps} steps: say “go on” to continue.",
            Outcome.FAILED: why,
        }.get(outcome)
        if note:
            self._add(Item(Kind.NOTE, note))
        told = [f"{seconds:.1f} s"] if seconds is not None else []
        if steps > 1:  # one step says nothing: an agent's turn is one too
            told.append(f"{steps} steps")
        used = self.last.told()
        self._add(Item(Kind.STATS, " · ".join(told + ([used] if used else []))))

    def _unsent(self) -> None:
        """What waited does not go."""
        for index in self._queued:
            self.items[index].queued, self.items[index].unsent = False, True
            self._change(index)
        self._queued.clear()

    # A kept conversation told again, in the GUI thread
    def _opened(self, opening: _Opening, why: str) -> None:
        """All of it at once, by the handlers of a live turn; then what was
        sent meanwhile goes."""
        self.opening = None
        for heard, given in opening.told:
            heard(*given)
        self._unsent()  # it waited as the program closed
        if why:
            self._add(Item(Kind.NOTE, why))
        self.model._emit_shown(self, self.model.usage_changed)
        for text, attachments in opening.held:
            self.send(text, attachments)

    def _replayed_began(self, said: Optional[Said]) -> None:
        self._answer = self._thinking = None
        self.last = Tokens()
        if said is not None:
            self._add(Item(Kind.PERSON, said.text, attachments=said.attachments))

    def _replayed_said(self, said: Said) -> None:
        self._queued.append(
            self._add(
                Item(Kind.PERSON, said.text, attachments=said.attachments, queued=True)
            )
        )

    def _replayed_end(
        self, outcome: Outcome, why: str, seconds: Optional[float]
    ) -> None:
        self._close(outcome, why, seconds)
        if outcome is not Outcome.ANSWERED:
            self._unsent()

    def _doing(self, phase: str) -> None:
        """What the turn running does now; a turn told again does nothing now."""
        if self.turn is not None:
            self._set_phase(phase)

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
    # The models, efforts and policies offered, the ones chosen, the finding
    models_changed = Signal()
    mode_changed = Signal()  # another mode shown: all of it anew
    history_changed = Signal()  # the kept conversations listed, or one renamed

    # Turns told something, from their threads or this one: the queue was empty
    _arrived = Signal()

    def __init__(
        self,
        session,
        providers: ProvidersModel,
        instructions: InstructionsModel,
        codex_settings: CodexSettingsModel,
        chats: Sequence[Chat],
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        # The settings: the built-in chat's servers, the person's
        # instructions, Codex's
        self.providers = providers
        self.instructions = instructions
        self.codex = codex_settings
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
        session.workspace.changed.connect(self._another_workspace)
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

    # What the mode shown offers, as its view model last read it (Mode.offered)
    def context_limit(self) -> Optional[int]:
        """The tokens the chosen model takes, when known."""
        return self.mode.offered.limit

    def context_share(self) -> Optional[float]:
        """How much of the context the chat fills (0…1), when its limit is
        known."""
        return share(self.usage.context, self.context_limit())

    def limits(self) -> Tuple[Limit, ...]:
        """How much of its agent's usage limits is left (Codex's windows);
        none for a chat whose agent tells none."""
        return self.mode.offered.limits

    def models(self) -> Sequence[Choice]:
        return self.mode.offered.models

    def chosen_model(self) -> Optional[str]:
        return self.mode.offered.model

    def choose_model(self, model: str) -> None:
        self.mode.chat.choose(model)
        self._models_changed(self.mode)

    def finding_models(self) -> bool:
        """Whether the mode's models are being found and not known yet."""
        return self.mode.offered.finding

    def efforts(self) -> Sequence[Choice]:
        """The reasoning efforts of the chosen model; none without a choice."""
        return self.mode.offered.efforts

    def chosen_effort(self) -> Optional[str]:
        return self.mode.offered.effort

    def choose_effort(self, effort: str) -> None:
        self.mode.chat.choose_effort(effort)
        self._models_changed(self.mode)

    def policies(self) -> Sequence[Choice]:
        """What the mode's agent may do without asking (its modes); none for
        a chat that never acts on its own."""
        return self.mode.offered.policies

    def chosen_policy(self) -> Optional[str]:
        return self.mode.offered.policy

    def choose_policy(self, policy: str) -> None:
        """At once, a turn running too (what asks first is the dock's)."""
        self.mode.chat.choose_policy(policy)
        self._models_changed(self.mode)

    def prepare(self) -> None:
        """The dock shows the mode: its chat gets ready in the background
        (Codex starts and makes a session, so its models are known) and its
        conversations of the workspace are listed; once."""
        self.mode.prepare(self.session.workspace.folder)
        self._models_changed(self.mode)

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
        self._models_changed(self.mode)  # its policy may be the settings' again

    # The conversations the mode shown keeps, of the window's workspace
    def find_chats(self) -> None:
        """List them anew: history_changed once found."""
        self.mode.find_chats(self.session.workspace.folder)

    def chats(self, search: str = "") -> List[Kept]:
        """As listed last, the newest first; those whose title holds search."""
        return matching(self.mode.history, search)

    def finding_chats(self) -> bool:
        """Whether they are being listed and not all found yet."""
        return self.mode.finding_chats

    def current_chat(self) -> Optional[str]:
        """The id of the conversation shown; None before its first message."""
        return self.mode.current()

    def open_chat(self, id: str) -> None:
        """Show a listed conversation in place of the one shown and go on
        with it (a turn running is stopped first)."""
        chat = next(chat for chat in self.mode.history if chat.id == id)
        self.mode.open(chat)

    def rename_chat(self, id: str, title: str) -> None:
        chat = next(chat for chat in self.mode.history if chat.id == id)
        self.mode.rename(chat, title)

    def renames(self) -> bool:
        """Whether the mode shown gives its chats other titles."""
        return self.mode.chat.renames()

    def answer(self, index: int, option: str) -> None:
        """The person's answer to what the agent of the mode shown asks (the
        item at index), an option's id."""
        self.mode.answer(index, option)
        self._show_changes()

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

    def _another_workspace(self) -> None:
        """The conversations listed are of another workspace now."""
        for mode in self.modes:
            mode.history = ()
            if mode.listing is not None:  # listed before: listed again
                mode.find_chats(self.session.workspace.folder)
        self.history_changed.emit()

    def _another_lab(self) -> None:
        for mode in self.modes:
            mode.chat.lab_changed()

    def _prompt_changed(self) -> None:
        """The bench or the person's instructions changed: the next turn makes
        the system prompt anew (a turn running keeps its own)."""
        for mode in self.modes:
            mode.chat.prompt_changed()

    def _models_changed(self, mode: Mode) -> None:
        """Read what the mode's chat offers now, and tell it: in the GUI
        thread, so what is read and what is told never part."""
        mode.offered = mode.chat.offered()
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
