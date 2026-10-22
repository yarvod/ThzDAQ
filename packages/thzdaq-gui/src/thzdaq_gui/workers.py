"""Background execution: instrument calls and measurements never block the UI.

Results come back as Qt signals; Qt queues them into the GUI thread because
the emitting thread differs from the receivers' thread.
"""

import logging
import queue
import threading
from typing import Any, Callable, Dict, Mapping, Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_core.data.store import MeasurementStore
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.runner import MeasurementRunner, RunObserver

logger = logging.getLogger(__name__)

Callback = Optional[Callable[[Any], None]]


class DeviceWorker(QObject):
    """One thread that runs instrument calls in order (manual control, polling)."""

    _done = Signal(object, object, object)  # callback, result, error
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "queue.Queue" = queue.Queue()
        self._done.connect(self._deliver)
        self._thread = threading.Thread(
            target=self._loop, name="DeviceWorker", daemon=True
        )
        self._thread.start()

    def submit(
        self,
        job: Callable[[], Any],
        on_result: Callback = None,
        on_error: Callback = None,
    ):
        self._queue.put((job, on_result, on_error))

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            job, on_result, on_error = item
            try:
                result = job()
            except Exception as e:
                logger.exception("Device job failed")
                self._done.emit(on_error, None, e)
            else:
                self._done.emit(on_result, result, None)
            # Callbacks hold widgets: their last reference must die in the GUI
            # thread (after delivery), never here, or Qt deletes a widget from
            # this thread and crashes
            del item, job, on_result, on_error
            result = None

    def _deliver(self, callback, result, error):
        if error is not None:
            if callback is not None:
                callback(error)
            else:
                self.error.emit(f"{error.__class__.__name__}: {error}")
        elif callback is not None:
            callback(result)

    def stop(self, timeout: float = 2.0):
        self._queue.put(None)
        self._thread.join(timeout)


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
        try:
            measurement = self._runner.run(procedure, comment=comment, devices=devices)
        except Exception as e:
            self.failed.emit(f"{e.__class__.__name__}: {e}")
            self.running_changed.emit(False)
            return
        self.finished.emit(measurement)
        self.running_changed.emit(False)

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
