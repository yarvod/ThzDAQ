"""The assistant's hints where the person types, on QtCore: code asked for
with Ctrl+I, the ghost text, a fix of what failed (assistant/hints.py says
what is asked and what of the answer is taken). The one owner of these calls
to the model: the server chosen for the assistant answers them.

Each question is a Request of whoever asked (the editor, a console's input).
The model's answer streams: the request tells what it does now (waiting for
the model's first word, thinking, writing) and for how long, what the model
thought and wrote so far; then it is answered, or failed with why, and ends.
The model is asked in a thread of its own, so nothing waits for it. What
that thread hears waits in the request's queue (Told), which the GUI thread
takes whole, woken only when the queue was empty: however fast the model
writes, a request tells its progress once per take. Cancelled, or gone with
whoever asked, a request hears nothing more: its queue is dropped and the
next piece the model sends stops the reply. Without a server nothing is
asked: the editors show why (NO_SERVER) and keep their hints off.
"""

import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance
from thzdaq_api import present
from thzdaq_api.errors import LabError

from thzdaq_gui.assistant import hints
from thzdaq_gui.assistant.provider import Client, Message, Provider, ProviderError
from thzdaq_gui.models.assistant import THINKING, WRITING, ProvidersModel

NO_SERVER = "Hints need the server of a model: add one in Assistant (its gear)"
UNKNOWN_DEVICES = "(not known now: the daemon does not answer)"
WAITING = "Waiting"  # for the model's first word
FIX = "Fix"  # what a fix asks, before the last line of its error


class Stopped(Exception):
    """The question was cancelled: its reply stops."""


class Told:
    """What the thread of one question hears, waiting for the GUI thread:
    pieces of the thought and of the answer, then the end. The thread tells,
    the GUI thread takes all of it at once (take); arrived wakes it, emitted
    only when nothing waited."""

    def __init__(self, arrived: SignalInstance):
        self._arrived = arrived
        self._lock = threading.Lock()
        self._thought: List[str] = []
        self._text: List[str] = []
        self._phase = ""  # what the piece told last makes it do
        self._end: Optional[Tuple[str, str]] = None  # (text taken, why it failed)
        self._dropped = False

    # In the question's thread
    def thought(self, piece: str) -> None:
        self._tell(self._thought, piece, THINKING)

    def heard(self, piece: str) -> None:
        self._tell(self._text, piece, WRITING)

    def ended(self, text: str, error: str) -> None:
        """Answered with text, or failed with error."""
        with self._lock:
            if self._dropped:
                return
            woken = self._empty()
            self._end = (text, error)
        if woken:
            self._arrived.emit(self)

    def _tell(self, pieces: List[str], piece: str, phase: str) -> None:
        with self._lock:
            if self._dropped:
                raise Stopped  # out of the provider's reply: it stops
            woken = self._empty()
            pieces.append(piece)
            self._phase = phase
        if woken:
            self._arrived.emit(self)

    def _empty(self) -> bool:
        return not (self._thought or self._text or self._end)

    # In the GUI thread
    def take(self) -> Tuple[str, str, str, Optional[Tuple[str, str]]]:
        """What waits: the thought and the text told since, joined, the
        phase they make ("": none told) and the end, once told."""
        with self._lock:
            found = ("".join(self._thought), "".join(self._text), self._phase)
            end, self._end = self._end, None
            self._thought, self._text, self._phase = [], [], ""
        return (*found, end)

    def drop(self) -> None:
        """Nobody listens any more: what waits goes, the next piece stops."""
        with self._lock:
            self._dropped = True
            self._thought, self._text, self._end = [], [], None


class Request(QObject):
    """One question to the model: what it does now and for how long, what
    it thought and wrote so far; it answers once, or fails, and ends."""

    progressed = Signal(str, str)  # the thought and the text added by one take
    answered = Signal(str)
    failed = Signal(str)
    ended = Signal()  # once: answered, failed or cancelled

    def __init__(
        self,
        hints_model: "HintsModel",
        provider: Optional[Provider],
        asked: str,
        parent: QObject,
    ):
        super().__init__(parent)
        self.hints = hints_model
        self.told = Told(hints_model._arrived)  # the thread's side of it
        self.asked = asked  # what it asks, in a line ("" for a ghost)
        self.model = provider.model if provider is not None else ""
        # Which server answers, in a line
        self.server = (
            f"{provider.model} on {provider.name} ({provider.url})"
            if provider is not None
            else ""
        )
        self.phase = WAITING
        self.thought = ""
        self.text = ""  # the answer so far, as the model writes it
        self.began = time.monotonic()

    def seconds(self) -> float:
        """Since it was asked."""
        return time.monotonic() - self.began

    def doing(self) -> str:
        """What it does now and for how long: Thinking… 4 s."""
        return f"{self.phase}… {self.seconds():.0f} s"

    def cancel(self) -> None:
        """Its answer is not wanted any more."""
        self.hints.forget(self)

    def take(self) -> Optional[Tuple[str, str]]:
        """What its thread told since, told once; the end, once it came."""
        thought, text, phase, end = self.told.take()
        if phase:
            self.phase = phase
        if thought or text:
            self.thought += thought
            self.text += text
            self.progressed.emit(thought, text)
        return end


class HintsModel(QObject):
    availability_changed = Signal(bool)
    # A question's queue had nothing and was told something (from its thread)
    _arrived = Signal(object)

    def __init__(self, session, providers: ProvidersModel, parent=None):
        super().__init__(parent)
        self.session = session
        self.providers = providers
        self._waiting: Dict[Told, Request] = {}
        # Queued even in the GUI thread: who asked hears after it connected
        self._arrived.connect(self._take, Qt.QueuedConnection)
        providers.changed.connect(
            lambda: self.availability_changed.emit(self.available())
        )

    def available(self) -> bool:
        return self.providers.chosen() is not None

    # Questions
    def write(
        self, where: str, code: str, start: int, end: int, asked: str, parent
    ) -> Request:
        """Code for what is asked at the cursor (or the selection [start,
        end)): answered with the whole text with it."""
        return self._ask(
            lambda system: hints.write_messages(system, where, code, start, end, asked),
            lambda answer: hints.written(code, start, end, answer),
            asked,
            parent,
        )

    def ghost(self, where: str, code: str, cursor: int, parent) -> Request:
        """What may follow the cursor: answered with it, "" when nothing does."""
        return self._ask(
            lambda system: hints.ghost_messages(system, where, code, cursor),
            lambda answer: hints.ghost_text(code, cursor, answer) or "",
            "",
            parent,
        )

    def fix(
        self, where: str, code: str, error: str, recent: Sequence[str], parent
    ) -> Request:
        """The code that failed, mended: answered with the whole of it."""
        last = error.strip().splitlines()[-1] if error.strip() else ""
        return self._ask(
            lambda system: hints.fix_messages(system, where, code, error, recent),
            lambda answer: hints.fixed(code, answer),
            f"{FIX}: {last}",
            parent,
        )

    def forget(self, request: Request) -> None:
        """A request on its way, cancelled: it ends, its thread hears no more."""
        if self._waiting.pop(request.told, None) is not None:
            request.told.drop()
            request.ended.emit()
            request.deleteLater()

    # Asking
    def _ask(
        self,
        messages: Callable[[str], Sequence[Message]],
        taken: Callable[[str], str],
        asked: str,
        parent,
    ) -> Request:
        provider = self.providers.chosen()
        request = Request(self, provider, asked, parent)
        told = request.told
        self._waiting[told] = request
        request.destroyed.connect(lambda *_: self._gone(told))
        if provider is None:
            told.ended("", NO_SERVER)
            return request
        client = Client(provider, self.providers.key(provider.name))
        sent = list(messages(hints.system(self._devices())))

        def run() -> None:
            try:
                reply = client.complete(sent, (), told.heard, thought=told.thought)
            except Stopped:
                return  # cancelled: nobody listens
            except ProviderError as e:
                told.ended("", str(e))
                return
            told.ended(taken(reply.text), "")

        threading.Thread(target=run, name="assistant hint", daemon=True).start()
        return request

    def _devices(self) -> str:
        try:
            return present.devices(self.session.devices())
        except LabError:
            return UNKNOWN_DEVICES

    def _gone(self, told: Told) -> None:
        """Whoever asked is gone, and the request with it."""
        if self._waiting.pop(told, None) is not None:
            told.drop()

    def _take(self, told: Told) -> None:
        request = self._waiting.get(told)
        if request is None:
            return  # cancelled, or gone with whoever asked
        end = request.take()
        if end is None or self._waiting.pop(told, None) is None:
            return  # going on; or cancelled by whoever heard its progress
        text, error = end
        if error:
            request.failed.emit(error)
        else:
            request.answered.emit(text)
        request.ended.emit()
        request.deleteLater()
