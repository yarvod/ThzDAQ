"""Background execution: instrument calls and measurements never block the UI.

Results come back as Qt signals; Qt queues them into the GUI thread because
the emitting thread differs from the receivers' thread.
"""

import logging
import threading
from typing import Any, Callable, Dict, Mapping, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.application.lanes import Lanes
from thzdaq_core.application.runner import MeasurementRunner, RunObserver

logger = logging.getLogger(__name__)

Callback = Optional[Callable[[Any], None]]


class DeviceWorker(QObject):
    """Manual control and polling of instruments in their lanes (one queue and
    thread per instrument, thzdaq_core.application.lanes); results come back
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


class _Forward(RunObserver):
    def __init__(self, runner: "QtRunner"):
        self.runner = runner

    def on_started(self, measurement):
        self.runner.started.emit(measurement)

    def on_record(self, table, record):
        self.runner.record.emit(table, record)

    def on_progress(self, done, total):
        self.runner.progress.emit(done, total)

    def on_log(self, message):
        self.runner.log.emit(message)


class QtRunner(QObject):
    """MeasurementRunner in a worker thread, events as Qt signals.

    Every measurement dock owns one, so measurements run side by side; the
    instruments they share are protected by the transport locks.
    """

    started = Signal(object)  # Measurement
    record = Signal(str, object)  # table, record
    progress = Signal(int, object)  # done, total or None
    log = Signal(str)
    finished = Signal(object)  # Measurement
    failed = Signal(str)  # could not start: missing device, bad parameters
    running_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner: Optional[MeasurementRunner] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        station,
        store: Optional[MeasurementStore],
        procedure: Procedure,
        devices: Optional[Mapping[str, str]] = None,
        comment: str = "",
    ) -> None:
        if self.running:
            raise RuntimeError("A measurement is already running")
        self._runner = MeasurementRunner(station, store, [_Forward(self)])
        self._thread = threading.Thread(
            target=self._run,
            args=(procedure, dict(devices or {}), comment),
            name=f"Measurement {procedure.name}",
            daemon=True,
        )
        self.running_changed.emit(True)
        self._thread.start()

    def _run(self, procedure: Procedure, devices: Dict[str, str], comment: str):
        # Whatever happens in the thread, the dock learns that it is over
        try:
            measurement = self._runner.run(procedure, comment=comment, devices=devices)
        except BaseException as e:
            self.failed.emit(f"{e.__class__.__name__}: {e}")
        else:
            self.finished.emit(measurement)
        finally:
            self.running_changed.emit(False)

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
