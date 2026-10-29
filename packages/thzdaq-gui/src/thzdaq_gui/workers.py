"""Background execution: instrument calls and operations never block the UI.

Results come back as Qt signals; Qt queues them into the GUI thread because
the emitting thread differs from the receivers' thread.
"""

import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_api.lanes import Lanes

logger = logging.getLogger(__name__)

Callback = Optional[Callable[[Any], None]]


class DeviceWorker(QObject):
    """Manual control and polling of instruments in their lanes (one queue and
    thread per instrument, thzdaq_api.lanes); results come back
    as Qt signals in the GUI thread."""

    _done = Signal(object, object, object)  # callback, result, error
    error = Signal(str)

    def __init__(self, parent=None, lanes: Optional[Lanes] = None):
        super().__init__(parent)
        self.lanes = lanes or Lanes()
        self._done.connect(self._deliver)

    def submit(
        self,
        job: Callable[[], Any],
        on_result: Callback = None,
        on_error: Callback = None,
        label: Optional[str] = None,
        key: Optional[str] = None,
    ):
        """label: the device the job talks to, named when it does not answer;
        key: its instrument, whose lane the job joins."""

        def deliver(result, error, on_result=on_result, on_error=on_error):
            # The signal keeps the callbacks: their last reference (they hold
            # widgets) dies in the GUI thread after delivery, never in a lane
            self._done.emit(on_result if error is None else on_error, result, error)

        self.lanes.submit(key or "", job, deliver, label)

    @property
    def pending(self) -> int:
        return self.lanes.pending

    def busy_for(self) -> float:
        return self.lanes.busy_for()

    @property
    def current(self) -> Optional[str]:
        return self.lanes.current

    @property
    def started_at(self) -> Optional[float]:
        return self.lanes.started_at

    def _deliver(self, callback, result, error):
        if error is not None:
            if callback is not None:
                callback(error)
            else:
                self.error.emit(f"{error.__class__.__name__}: {error}")
        elif callback is not None:
            callback(result)

    def stop(self, timeout: float = 2.0):
        self.lanes.stop(timeout)


class HangWatch(QObject):
    """Manual control waits while a device does not answer: says so on every
    look (message), and once per hang in the event log."""

    message = Signal(str)

    def __init__(self, worker: DeviceWorker, limit_s: float, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.limit_s = limit_s
        self._reported: Optional[float] = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(2000)

    def check(self) -> None:
        waiting = self.worker.busy_for()
        if waiting <= self.limit_s:
            self._reported = None
            return
        device = self.worker.current or "A device"
        self.message.emit(
            f"{device} has not answered for {waiting:.0f} s; manual control waits. "
            "Reset its connection in Setup → Connections."
        )
        if self._reported != self.worker.started_at:
            self._reported = self.worker.started_at
            logger.warning(
                f"{device} does not answer: manual control and monitors wait for it"
            )
