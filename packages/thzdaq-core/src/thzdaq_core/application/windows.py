"""The main windows that listen, and what agents ask of them (thzdaq_api.ui).

A window is a client whose event stream names its id. A call goes to the
window it names, else to the one a person was at last (told by
window_active), else to the one that came last. It is asked with an event
(ui_requested) and waits, outside every lock, for the window to answer
(answer_ui) or for UI_S to pass.
"""

import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import msgspec
from thzdaq_api.daemon import ClientInfo
from thzdaq_api.errors import ErrorCode, Failure, LabError
from thzdaq_api.events import UiRequested
from thzdaq_api.operation import Operation
from thzdaq_api.ui import UI_S

from thzdaq_core.application.events import EventBus

NO_WINDOW = "No ThzDAQ window is open"
OPEN_ONE = "a person opens one: thzdaq gui"


class _Asked:
    def __init__(self, operation: Operation):
        self.operation = operation
        self.answered = threading.Event()
        self.result: Any = None
        self.failure: Optional[Failure] = None


class Windows:
    def __init__(self, events: EventBus, clients: Callable[[], Iterable[ClientInfo]]):
        """clients: who listens now (the daemon's process)."""
        self.events = events
        self.clients = clients
        self._active: List[str] = []  # windows a person was at, the last one last
        self._asked: Dict[int, _Asked] = {}
        self._last = 0
        self._lock = threading.Lock()

    def open(self) -> Tuple[str, ...]:
        """The windows that listen, the one a person was at last first."""
        listening = list(dict.fromkeys(c.window for c in self.clients() if c.window))
        with self._lock:
            active = [w for w in reversed(self._active) if w in listening]
        return tuple(active + [w for w in reversed(listening) if w not in active])

    def activated(self, window: str) -> None:
        with self._lock:
            if window in self._active:
                self._active.remove(window)
            self._active.append(window)

    def target(self, window: Optional[str]) -> str:
        """The window a call goes to; LabError NOT_FOUND when it is not open."""
        found = self.open()
        if not found:
            raise LabError(ErrorCode.NOT_FOUND, NO_WINDOW, OPEN_ONE)
        if window is None:
            return found[0]
        if window not in found:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"No window {window} is open",
                f"open: {', '.join(found)}",
            )
        return window

    def ask(self, operation: Operation, origin: str) -> Any:
        """Ask the window the operation names (window: None for the one a
        person was at last) and wait for its result."""
        window = self.target(operation.window)
        operation = msgspec.structs.replace(operation, window=window)
        asked = _Asked(operation)
        with self._lock:
            self._last += 1
            id = self._last
            self._asked[id] = asked
        try:
            self.events.publish(
                UiRequested(
                    id, window, operation.name, msgspec.to_builtins(operation), origin
                )
            )
            if not asked.answered.wait(UI_S):
                raise LabError(
                    ErrorCode.NOT_FOUND,
                    f"The window {window} did not answer in {UI_S:g} s",
                    "it may be closing or busy: ask again",
                )
        finally:
            with self._lock:
                self._asked.pop(id, None)
        if asked.failure is not None:
            raise LabError.from_failure(asked.failure)
        try:
            return msgspec.convert(asked.result, operation.result_type())
        except msgspec.ValidationError as e:
            raise LabError(
                ErrorCode.INTERNAL, f"The window answered {operation.name} wrong: {e}"
            ) from None

    def answer(self, id: int, result: Any, failure: Optional[Failure]) -> None:
        """A window's answer; LabError NOT_FOUND when nothing waits for it (it
        came too late)."""
        with self._lock:
            asked = self._asked.get(id)
        if asked is None:
            raise LabError(ErrorCode.NOT_FOUND, f"Nothing waits as {id}: too late")
        asked.result, asked.failure = result, failure
        asked.answered.set()
