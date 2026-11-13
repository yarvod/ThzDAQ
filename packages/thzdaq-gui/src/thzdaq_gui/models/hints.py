"""The assistant's hints where the person types, on QtCore: code asked for
with Ctrl+I, the ghost text, a fix of what failed (assistant/hints.py says
what is asked and what of the answer is taken). The one owner of these calls
to the model: the server chosen for the assistant answers them.

Each question is a Request of whoever asked (the editor, a console's input):
answered, or failed with why, in the GUI thread; cancelled, or gone with
whoever asked, its answer is dropped. The model is asked in a thread of its
own, so nothing waits for it. Without a server nothing is asked: the
editors show why (NO_SERVER) and keep their hints off.
"""

import threading
from typing import Callable, Dict, Optional, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from thzdaq_api import present
from thzdaq_api.errors import LabError

from thzdaq_gui.assistant import hints
from thzdaq_gui.assistant.provider import Client, Message, ProviderError
from thzdaq_gui.models.assistant import ProvidersModel

NO_SERVER = "Hints need the server of a model: add one in Assistant (its gear)"
UNKNOWN_DEVICES = "(not known now: the daemon does not answer)"


class Request(QObject):
    """One question to the model; it answers once, or fails."""

    answered = Signal(str)
    failed = Signal(str)

    def __init__(self, hints_model: "HintsModel", parent: QObject):
        super().__init__(parent)
        self.hints = hints_model
        self.token = object()  # what its answer comes back with

    def cancel(self) -> None:
        """Its answer is not wanted any more."""
        self.hints.forget(self)


class HintsModel(QObject):
    availability_changed = Signal(bool)
    # From a question's thread: (its token, the text taken, why it failed or "")
    _answered = Signal(object, str, str)

    def __init__(self, session, providers: ProvidersModel, parent=None):
        super().__init__(parent)
        self.session = session
        self.providers = providers
        self._waiting: Dict[object, Request] = {}
        # Queued even in the GUI thread: who asked hears after it connected
        self._answered.connect(self._deliver, Qt.QueuedConnection)
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
            parent,
        )

    def ghost(self, where: str, code: str, cursor: int, parent) -> Request:
        """What may follow the cursor: answered with it, "" when nothing does."""
        return self._ask(
            lambda system: hints.ghost_messages(system, where, code, cursor),
            lambda answer: hints.ghost_text(code, cursor, answer) or "",
            parent,
        )

    def fix(
        self, where: str, code: str, error: str, recent: Sequence[str], parent
    ) -> Request:
        """The code that failed, mended: answered with the whole of it."""
        return self._ask(
            lambda system: hints.fix_messages(system, where, code, error, recent),
            lambda answer: hints.fixed(code, answer),
            parent,
        )

    def forget(self, request: Request) -> None:
        if self._waiting.pop(request.token, None) is not None:
            request.deleteLater()

    # Asking
    def _ask(
        self,
        messages: Callable[[str], Sequence[Message]],
        taken: Callable[[str], str],
        parent,
    ) -> Request:
        request = Request(self, parent)
        token = request.token
        self._waiting[token] = request
        request.destroyed.connect(lambda *_: self._waiting.pop(token, None))
        provider = self.providers.chosen()
        if provider is None:
            self._answered.emit(token, "", NO_SERVER)
            return request
        client = Client(provider, self.providers.key(provider.name))
        asked = list(messages(hints.system(self._devices())))

        def run() -> None:
            try:
                reply = client.complete(asked, (), lambda piece: None, stream=False)
                self._answered.emit(token, taken(reply.text), "")
            except ProviderError as e:
                self._answered.emit(token, "", str(e))

        threading.Thread(target=run, name="assistant hint", daemon=True).start()
        return request

    def _devices(self) -> str:
        try:
            return present.devices(self.session.devices())
        except LabError:
            return UNKNOWN_DEVICES

    def _deliver(self, token: object, text: str, error: str) -> None:
        request: Optional[Request] = self._waiting.pop(token, None)
        if request is None:
            return  # cancelled, or gone with whoever asked
        if error:
            request.failed.emit(error)
        else:
            request.answered.emit(text)
        request.deleteLater()
