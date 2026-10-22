import logging
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from thzdaq_core.data.measurement import (
    CANCELLED,
    COMPLETED,
    FAILED,
    DeviceUse,
    Measurement,
)
from thzdaq_core.data.store import MeasurementStore
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.procedure import Capabilities, Procedure

logger = logging.getLogger(__name__)


class Cancelled(Exception):
    """Raised inside run() when the measurement is stopped."""


class StationLike(Protocol):
    """What the runner needs from a bench (Station implements it)."""

    def require(
        self, devices: Mapping[str, str], requirements: Mapping[str, Capabilities]
    ) -> Dict[str, Any]:
        ...

    def device_use(self, ref: str) -> DeviceUse:
        ...

    def snapshot(self) -> Dict[str, Any]:
        ...


class RunObserver:
    """Hooks for UIs and loggers; every method is optional."""

    def on_started(self, measurement: Measurement) -> None:
        ...

    def on_record(self, table: str, record: Dict[str, Any]) -> None:
        ...

    def on_progress(self, done: int, total: Optional[int]) -> None:
        ...

    def on_log(self, message: str) -> None:
        ...

    def on_finished(self, measurement: Measurement) -> None:
        ...


class Context:
    """Everything a running procedure may touch."""

    def __init__(
        self,
        devices: Mapping[str, Any],
        measurement: Measurement,
        emit: Callable[..., None],
        cancel_event: threading.Event,
        procedure: Optional[Procedure] = None,
        autosave: Optional[Callable[[], None]] = None,
        total: Optional[int] = None,
    ):
        self.devices = devices
        self.measurement = measurement
        self.procedure = procedure
        self._emit = emit
        self._cancel = cancel_event
        self._autosave = autosave
        self._cleanups: List[Callable[[], None]] = []
        self.done = 0
        self.total = total

    def __getitem__(self, slot: str) -> Any:
        return self.devices[slot]

    def record(self, table: str, **values: Any) -> Dict[str, Any]:
        record = dict(values)
        if table not in self.measurement.tables and self.procedure is not None:
            self.measurement.table(table, self.procedure.table_titles.get(table, ""))
        overrides = self.procedure.columns if self.procedure is not None else None
        self.measurement.append(table, record, overrides)
        if self._autosave is not None:
            self._autosave()
        self._emit("on_record", table, record)
        return record

    def result(self, key: str, value: Any) -> None:
        """Final values of the run (fit results, summary)."""
        self.measurement.results[key] = value

    def progress(self, done: Optional[int] = None, total: Optional[int] = None) -> None:
        if total is not None:
            self.total = total
        self.done = self.done + 1 if done is None else done
        self._emit("on_progress", self.done, self.total)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled

    def sleep(self, seconds: float) -> None:
        """Sleep that wakes up immediately on cancel."""
        if seconds > 0 and self._cancel.wait(seconds):
            raise Cancelled
        self.check_cancel()

    def log(self, message: str) -> None:
        logger.info(f"[{self.measurement.procedure}] {message}")
        self._emit("on_log", message)

    def on_exit(self, callback: Callable[[], None]) -> None:
        """Restore hardware state when the run ends, in reverse order of registration."""
        self._cleanups.append(callback)

    def _run_cleanups(self) -> List[str]:
        errors = []
        for callback in reversed(self._cleanups):
            try:
                callback()
            except Exception as e:
                logger.exception(f"[{self.measurement.procedure}] cleanup failed")
                errors.append(f"cleanup: {e}")
        self._cleanups.clear()
        return errors


class MeasurementRunner:
    """Runs procedures against a station: devices, measurement, file, cleanup, status.

    run() blocks; call it from a worker thread and cancel() from another.
    """

    def __init__(
        self,
        station: StationLike,
        store: Optional[MeasurementStore] = None,
        observers: Sequence[RunObserver] = (),
        autosave_interval: float = 5.0,
    ):
        self.station = station
        self.store = store
        self.observers: List[RunObserver] = list(observers)
        self.autosave_interval = autosave_interval
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.current: Optional[Measurement] = None

    def _emit(self, method: str, *args: Any) -> None:
        for observer in self.observers:
            try:
                getattr(observer, method)(*args)
            except Exception:
                # A broken plot must not stop the measurement
                logger.exception(f"Observer {observer!r}.{method} failed")

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def run(
        self,
        procedure: Procedure,
        comment: str = "",
        devices: Optional[Mapping[str, str]] = None,
    ) -> Measurement:
        """devices maps procedure slots to station devices, e.g. {"bias": "sis_bias_1"}.

        A slot without a device uses the station device of the same name.
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Another measurement is running on this runner")
        try:
            return self._run(procedure, comment, dict(devices or {}))
        finally:
            self._lock.release()

    def _run(
        self, procedure: Procedure, comment: str, devices: Dict[str, str]
    ) -> Measurement:
        procedure.validate()
        required = procedure.slots()
        unknown = set(devices) - set(procedure.requires) - set(required)
        if unknown:
            raise ProcedureError(f"{procedure.name} has no slots {sorted(unknown)}")
        refs = {slot: devices.get(slot) or slot for slot in required}
        # Fails before any file exists when a device is missing or unsuitable
        found = self.station.require(refs, required)
        self._cancel.clear()
        measurement = Measurement(
            procedure=procedure.name,
            title=procedure.title,
            parameters=procedure.to_json(),
            comment=comment,
            devices={slot: self.station.device_use(ref) for slot, ref in refs.items()},
            station=self.station.snapshot(),
        )
        self.current = measurement
        saved = [0.0]

        def save(force: bool = False) -> None:
            if self.store is None:
                return
            if force or time.monotonic() - saved[0] >= self.autosave_interval:
                try:
                    self.store.save(measurement)
                except OSError:
                    logger.exception(f"[{procedure.name}] autosave failed")
                saved[0] = time.monotonic()

        ctx = Context(
            found, measurement, self._emit, self._cancel, procedure, save,
            procedure.estimate_steps(),
        )  # fmt: skip
        status, error = COMPLETED, None
        try:
            save(force=True)
            self._emit("on_started", measurement)
            procedure.run(ctx)
        except Cancelled:
            status = CANCELLED
        except Exception as e:
            logger.exception(f"[{procedure.name}] failed")
            status, error = FAILED, f"{e.__class__.__name__}: {e}"
            measurement.metadata["traceback"] = traceback.format_exc()
        finally:
            cleanup_errors = ctx._run_cleanups()
            if cleanup_errors:
                measurement.metadata["cleanup_errors"] = cleanup_errors
            measurement.finish(status, error)
            save(force=True)
            self.current = None
            self._emit("on_finished", measurement)
        return measurement
