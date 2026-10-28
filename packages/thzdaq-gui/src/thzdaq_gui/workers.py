"""Background execution: instrument calls and measurements never block the UI.

Results come back as Qt signals; Qt queues them into the GUI thread because
the emitting thread differs from the receivers' thread.
"""

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_core.data.store import MeasurementStore
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.runner import MeasurementRunner, RunObserver

logger = logging.getLogger(__name__)

Callback = Optional[Callable[[Any], None]]


class _Lane:
    """One thread with its queue: the jobs of one instrument, in order."""

    def __init__(self, worker: "DeviceWorker", key: str):
        self.worker = worker
        self.queue: "queue.Queue" = queue.Queue()
        self.started: Optional[float] = None
        self.label: Optional[str] = None
        name = f"DeviceWorker {key}" if key else "DeviceWorker"
        self.thread = threading.Thread(target=self.loop, name=name, daemon=True)
        self.thread.start()

    def loop(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            job, on_result, on_error, label = item
            self.label = label
            self.started = time.monotonic()
            try:
                result = job()
            except Exception as e:
                logger.exception(f"Device job failed{f' ({label})' if label else ''}")
                self.worker._done.emit(on_error, None, e)
            else:
                self.worker._done.emit(on_result, result, None)
            finally:
                self.started = None
                self.label = None
            # Callbacks hold widgets: their last reference must die in the GUI
            # thread (after delivery), never here, or Qt deletes a widget from
            # this thread and crashes
            del item, job, on_result, on_error
            result = None


class DeviceWorker(QObject):
    """Manual control and polling of instruments, one queue per instrument.

    Jobs of one instrument run in order in its own thread; instruments do not
    wait for each other, so a slow or hung power meter does not hold the SIS
    monitor. Instruments sharing a connection (a Prologix) still take turns
    on its lock.
    """

    _done = Signal(object, object, object)  # callback, result, error
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lanes: Dict[str, _Lane] = {}
        self._lock = threading.Lock()
        self._done.connect(self._deliver)
        self._lane("")  # jobs without an instrument

    def _lane(self, key: str) -> _Lane:
        with self._lock:
            lane = self._lanes.get(key)
            if lane is None:
                lane = self._lanes[key] = _Lane(self, key)
            return lane

    def submit(
        self,
        job: Callable[[], Any],
        on_result: Callback = None,
        on_error: Callback = None,
        label: Optional[str] = None,
        key: Optional[str] = None,
    ):
        """label: the device the job talks to, named when it does not answer;
        key: its instrument, whose queue the job joins."""
        self._lane(key or "").queue.put((job, on_result, on_error, label))

    @property
    def pending(self) -> int:
        return sum(lane.queue.qsize() for lane in list(self._lanes.values()))

    def _slowest(self) -> Tuple[Optional[float], Optional[str]]:
        """(start, label) of the longest job in progress; lanes change meanwhile."""
        busy = []
        for lane in list(self._lanes.values()):
            started, label = lane.started, lane.label
            if started is not None:
                busy.append((started, label))
        return min(busy, key=lambda item: item[0], default=(None, None))

    def busy_for(self) -> float:
        """Seconds the longest job in progress has been running (0 when idle)."""
        started, _ = self._slowest()
        return 0.0 if started is None else time.monotonic() - started

    @property
    def current(self) -> Optional[str]:
        """Label of the longest job in progress."""
        return self._slowest()[1]

    @property
    def started_at(self) -> Optional[float]:
        """When the longest job in progress started (monotonic), None when idle."""
        return self._slowest()[0]

    def _deliver(self, callback, result, error):
        if error is not None:
            if callback is not None:
                callback(error)
            else:
                self.error.emit(f"{error.__class__.__name__}: {error}")
        elif callback is not None:
            callback(result)

    def stop(self, timeout: float = 2.0):
        lanes = list(self._lanes.values())
        for lane in lanes:
            lane.queue.put(None)
        deadline = time.monotonic() + timeout
        for lane in lanes:
            lane.thread.join(max(0.0, deadline - time.monotonic()))


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
