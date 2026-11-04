import itertools
import logging
import threading
import time
import traceback
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

import msgspec
from thzdaq_api.measurement_file import (
    CANCELLED,
    COMPLETED,
    FAILED,
    INTERRUPTED,
    DeviceUse,
    Measurement,
)
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.ports import MeasurementRepository
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.procedure import Capabilities, Procedure

logger = logging.getLogger(__name__)


# Numbers of measurements that are not saved (no store)
_LOCAL_IDS = itertools.count(1)


PLOTS = "plots"  # metadata: plots a run added while it ran


class Cancelled(Exception):
    """Raised inside run() when the measurement is stopped."""


class Interrupted(Exception):
    """Raised inside run() when what drives it is gone (a script that fell
    silent): it ends interrupted, and restores what it changed."""


class Failed(Exception):
    """Raised inside run() for a failure told by what drives it (a script's
    error): it ends failed with this message and the given traceback."""

    def __init__(self, message: str, traceback: str = ""):
        super().__init__(message)
        self.traceback = traceback


class StationLike(Protocol):
    """What the runner needs from a bench (Station implements it)."""

    def require(
        self,
        devices: Mapping[str, str],
        requirements: Mapping[str, Capabilities],
        pause: Callable[[float], None],
        planned: Iterable[Tuple[str, str, Sequence[float]]] = (),
        told: Optional[Callable[[str, str, float], None]] = None,
    ) -> Dict[str, Any]:
        ...

    def device_use(self, ref: str) -> DeviceUse:
        ...

    def snapshot(self, refs: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        ...


class RampPause:
    """How the ramps of a run's devices wait between steps: a cancel stops a
    ramp at once while the run goes; what the run restores at its end ramps to
    the end."""

    def __init__(self, cancel_event: threading.Event):
        self._cancel = cancel_event
        self.restoring = False

    def __call__(self, seconds: float) -> None:
        if self.restoring:
            time.sleep(seconds)
        elif self._cancel.wait(seconds):
            raise Cancelled


class RunObserver:
    """Hooks for UIs and loggers; every method is optional."""

    def on_started(self, measurement: Measurement) -> None:
        ...

    def on_record(self, table: str, record: Dict[str, Any]) -> None:
        ...

    def on_flush(self) -> None:
        """Records held back to go together go now."""

    def on_set(self, ref: str, key: str, value: float) -> None:
        """The run set a quantity of a device (a point of its sweep)."""

    def on_plot(self, plot: PlotInfo) -> None:
        """The run draws another plot from now on."""

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

    def record(self, table: str, /, **values: Any) -> Dict[str, Any]:
        record = dict(values)
        if table not in self.measurement.tables and self.procedure is not None:
            self.measurement.table(table, self.procedure.table_titles.get(table, ""))
        overrides = self.procedure.columns if self.procedure is not None else None
        self.measurement.append(table, record, overrides)
        if self._autosave is not None:
            self._autosave()
        self._emit("on_record", table, record)
        return record

    def flush(self) -> None:
        """The records so far are told now, not with the next ones (the end of
        a script's call of records)."""
        self._emit("on_flush")

    def plot(self, plot: PlotInfo) -> None:
        """Another plot of the run's records, drawn from now on and kept in
        its metadata."""
        self.measurement.metadata.setdefault(PLOTS, []).append(
            msgspec.to_builtins(plot)
        )
        self._emit("on_plot", plot)

    def told(self, ref: str, key: str, value: float) -> None:
        """The run set a quantity another way than through its devices (a
        script's set through the daemon)."""
        self._emit("on_set", ref, key, value)

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

    def now(self) -> str:
        """Wall time, ISO with milliseconds: the time stamp of a record."""
        return wall_time()

    def monotonic(self) -> float:
        """Seconds on a clock that never goes back: intervals within the run."""
        return time.monotonic()

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


def slot_devices(procedure: Procedure, devices: Mapping[str, str]) -> Dict[str, str]:
    """The device of every slot of a run: as given, else the station device
    named like the slot."""
    required = procedure.slots()
    unknown = set(devices) - set(procedure.requires) - set(required)
    if unknown:
        raise ProcedureError(f"{procedure.name} has no slots {sorted(unknown)}")
    return {slot: devices.get(slot) or slot for slot in required}


class MeasurementRunner:
    """Runs procedures against a station: devices, measurement, file, cleanup, status.

    run() blocks; call it from a worker thread and cancel() from another.
    """

    def __init__(
        self,
        station: StationLike,
        store: Optional[MeasurementRepository] = None,
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

    def _told(self, ref: str, key: str, value: float) -> None:
        self._emit("on_set", ref, key, value)

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
        measurement_id: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Measurement:
        """devices maps procedure slots to station devices, e.g. {"bias": "sis_bias_1"}.

        A slot without a device uses the station device of the same name.
        measurement_id: the number given by whoever took the devices for it;
        None: the store's next. metadata: what the measurement notes from its
        start (the copy of the profile in its workspace).
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Another measurement is running on this runner")
        try:
            return self._run(
                procedure, comment, dict(devices or {}), measurement_id, metadata
            )
        finally:
            self._lock.release()

    def _run(
        self,
        procedure: Procedure,
        comment: str,
        devices: Dict[str, str],
        measurement_id: Optional[int],
        metadata: Optional[Mapping[str, Any]],
    ) -> Measurement:
        procedure.validate()
        required = procedure.slots()
        refs = slot_devices(procedure, devices)
        self._cancel.clear()
        ramps = RampPause(self._cancel)
        # Fails before any file exists when a device is missing or unsuitable,
        # or the run would set it beyond its limits
        found = self.station.require(
            refs, required, ramps, procedure.planned(), self._told
        )
        measurement = Measurement(
            procedure=procedure.name,
            title=procedure.title,
            parameters=procedure.to_json(),
            comment=comment,
            devices={slot: self.station.device_use(ref) for slot, ref in refs.items()},
            station=self.station.snapshot(refs.values()),
            started=wall_time(),
            metadata=dict(metadata or {}),
        )
        if measurement_id is not None:
            measurement.id = measurement_id
        else:
            measurement.id = self.store.next_id() if self.store else next(_LOCAL_IDS)
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
        except Interrupted as e:
            status, error = INTERRUPTED, str(e)
        except Failed as e:
            status, error = FAILED, str(e)
            measurement.metadata["traceback"] = e.traceback
        except Exception as e:
            logger.exception(f"[{procedure.name}] failed")
            status, error = FAILED, f"{e.__class__.__name__}: {e}"
            measurement.metadata["traceback"] = traceback.format_exc()
        finally:
            ramps.restoring = True
            cleanup_errors = ctx._run_cleanups()
            if cleanup_errors:
                measurement.metadata["cleanup_errors"] = cleanup_errors
            measurement.finish(status, wall_time(), error)
            save(force=True)
            self.current = None
            self._emit("on_finished", measurement)
        return measurement
