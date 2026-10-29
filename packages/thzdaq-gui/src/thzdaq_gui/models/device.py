"""A device as its dock works with it: read, set and act through the lab in the
background, and the readings of polls as the lab tells them.

The calls of a device go one after another in its instrument's queue
(session.calls); devices do not wait for each other.
"""

from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api import events
from thzdaq_api.devices import (
    CallAction,
    CancelPoll,
    DeviceInfo,
    Poll,
    ReadDevice,
    SetQuantity,
    SubscribePoll,
)
from thzdaq_api.lab import Lab
from thzdaq_api.operation import Operation

Callback = Optional[Callable[[Any], None]]


def _keys(keys: Optional[Sequence[str]]) -> Optional[Tuple[str, ...]]:
    return None if keys is None else tuple(keys)


class DeviceModel(QObject):
    values = Signal(object)  # Dict[str, Value]: a reading, asked for or polled
    read_failed = Signal(str)
    set_done = Signal(str, object)  # key, the value set (SI)
    set_failed = Signal(str, object, str)  # key, the value asked, why not
    acted = Signal(str, object)  # action, what it returned: a value or a Trace
    action_failed = Signal(str, str)  # action, why

    def __init__(self, session, info: DeviceInfo, parent=None):
        super().__init__(parent)
        self.session = session
        self.ref = info.ref
        self.title = info.title
        self.lane = info.instrument  # the queue its calls join
        self._poll: Optional[Tuple[Lab, Poll]] = None  # the lab that polls
        self._polls = 0  # counts changes: an answer to an earlier poll is let go
        session.bridge.values.connect(self._heard)
        session.bridge.read_failed.connect(self._poll_failed)

    def read(self, keys: Optional[Sequence[str]] = None) -> None:
        """Every readable quantity, or the keys given."""
        self._call(
            ReadDevice(ref=self.ref, keys=_keys(keys)),
            lambda reading: self.values.emit(reading.values),
            lambda error: self.read_failed.emit(str(error)),
        )

    def set(self, key: str, value: Any) -> None:
        self._call(
            SetQuantity(ref=self.ref, key=key, value=value),
            lambda done: self.set_done.emit(key, done.value),
            lambda error: self.set_failed.emit(key, value, str(error)),
        )

    def call(self, action: str, arguments: Optional[Mapping[str, Any]] = None) -> None:
        self._call(
            CallAction(ref=self.ref, action=action, arguments=dict(arguments or {})),
            lambda done: self.acted.emit(action, done.result),
            lambda error: self.action_failed.emit(action, str(error)),
        )

    def poll(self, interval: float, keys: Optional[Sequence[str]] = None) -> None:
        """Readings every interval seconds until stop_polling; called again, with
        this interval and these keys instead."""
        self.stop_polling()
        number, lab = self._polls, self.session.lab
        self._call(
            SubscribePoll(ref=self.ref, interval=interval, keys=_keys(keys)),
            lambda poll: self._subscribed(lab, poll, number),
            lambda error: self.read_failed.emit(str(error)),
        )

    def stop_polling(self) -> None:
        self._polls += 1
        if self._poll is not None:
            lab, poll = self._poll
            self._poll = None
            self._call(CancelPoll(id=poll.id), lab=lab)

    def _subscribed(self, lab: Lab, poll: Poll, number: int) -> None:
        if number == self._polls:
            self._poll = (lab, poll)
        else:  # stopped or changed while it was asked for
            self._call(CancelPoll(id=poll.id), lab=lab)

    def _heard(self, body: events.Values) -> None:
        if body.ref == self.ref:
            self.values.emit(body.values)

    def _poll_failed(self, body: events.ReadFailed) -> None:
        if body.ref == self.ref and self._poll is not None:
            self.read_failed.emit(body.message)

    def _call(
        self,
        operation: Operation,
        done: Callback = None,
        failed: Callback = None,
        lab: Optional[Lab] = None,
    ) -> None:
        lab = lab or self.session.lab
        self.session.calls.submit(
            lambda: lab.call(operation), done, failed, self.title, key=self.lane
        )
