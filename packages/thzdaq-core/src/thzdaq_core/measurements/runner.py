import logging
import threading
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from thzdaq_core.data.dataset import CANCELLED, COMPLETED, FAILED, Dataset
from thzdaq_core.data.store import DatasetWriter, DataStore
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.procedure import Capabilities, Procedure

logger = logging.getLogger(__name__)


class Cancelled(Exception):
    """Raised inside run() when the measurement is stopped."""


class StationLike(Protocol):
    """What the runner needs from a bench (Station implements it)."""

    def require(self, requirements: Mapping[str, Capabilities]) -> Dict[str, Any]:
        ...

    def snapshot(self) -> Dict[str, Any]:
        ...


class RunObserver:
    """Hooks for UIs and loggers; every method is optional."""

    def on_started(self, dataset: Dataset) -> None:
        ...

    def on_record(self, stream: str, record: Dict[str, Any]) -> None:
        ...

    def on_progress(self, done: int, total: Optional[int]) -> None:
        ...

    def on_log(self, message: str) -> None:
        ...

    def on_finished(self, dataset: Dataset) -> None:
        ...


class Context:
    """Everything a running procedure may touch."""

    def __init__(
        self,
        ports: Mapping[str, Any],
        dataset: Dataset,
        emit: Callable[..., None],
        cancel_event: threading.Event,
        writer: Optional[DatasetWriter] = None,
        total: Optional[int] = None,
    ):
        self.ports = ports
        self.dataset = dataset
        self._emit = emit
        self._cancel = cancel_event
        self._writer = writer
        self._cleanups: List[Callable[[], None]] = []
        self.done = 0
        self.total = total

    def __getitem__(self, role: str) -> Any:
        return self.ports[role]

    def record(self, stream: str, **values: Any) -> Dict[str, Any]:
        record = dict(values)
        self.dataset.append(stream, record)
        if self._writer is not None:
            self._writer.write_record(stream, record)
        self._emit("on_record", stream, record)
        return record

    def result(self, key: str, value: Any) -> None:
        """Final values of the run (fit results, summary)."""
        self.dataset.results[key] = value

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
        logger.info(f"[{self.dataset.procedure}] {message}")
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
                logger.exception(f"[{self.dataset.procedure}] cleanup failed")
                errors.append(f"cleanup: {e}")
        self._cleanups.clear()
        return errors


class MeasurementRunner:
    """Runs procedures against a station: ports, dataset, file, cleanup, status.

    run() blocks; call it from a worker thread and cancel() from another.
    """

    def __init__(
        self,
        station: StationLike,
        store: Optional[DataStore] = None,
        observers: Sequence[RunObserver] = (),
    ):
        self.station = station
        self.store = store
        self.observers: List[RunObserver] = list(observers)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.current: Optional[Dataset] = None

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
        roles: Optional[Mapping[str, str]] = None,
    ) -> Dataset:
        """roles maps procedure roles to station roles, e.g. {"bias": "sis1"}."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Another measurement is running on this runner")
        try:
            return self._run(procedure, comment, dict(roles or {}))
        finally:
            self._lock.release()

    def _run(
        self, procedure: Procedure, comment: str, roles: Dict[str, str]
    ) -> Dataset:
        procedure.validate()
        required = procedure.roles()
        unknown = set(roles) - set(procedure.requires) - set(required)
        if unknown:
            raise ProcedureError(f"{procedure.name} has no roles {sorted(unknown)}")
        # Fails before any file exists when the bench lacks a role
        station_ports = self.station.require(
            {roles.get(role, role): caps for role, caps in required.items()}
        )
        ports = {role: station_ports[roles.get(role, role)] for role in required}
        self._cancel.clear()
        dataset = Dataset(
            procedure=procedure.name,
            title=procedure.title,
            parameters=procedure.to_json(),
            station=self.station.snapshot(),
            comment=comment,
            metadata={"roles": {role: roles.get(role, role) for role in required}},
        )
        writer = self.store.writer(dataset) if self.store is not None else None
        self.current = dataset
        ctx = Context(
            ports, dataset, self._emit, self._cancel, writer, procedure.estimate_steps()
        )
        status, error = COMPLETED, None
        try:
            if writer is not None:
                writer.write_header(dataset)
            self._emit("on_started", dataset)
            procedure.run(ctx)
        except Cancelled:
            status = CANCELLED
        except Exception as e:
            logger.exception(f"[{procedure.name}] failed")
            status, error = FAILED, f"{e.__class__.__name__}: {e}"
            dataset.metadata["traceback"] = traceback.format_exc()
        finally:
            cleanup_errors = ctx._run_cleanups()
            if cleanup_errors:
                dataset.metadata["cleanup_errors"] = cleanup_errors
            dataset.finish(status, error)
            if writer is not None:
                try:
                    writer.write_footer(dataset)
                finally:
                    writer.close()
                dataset.metadata["path"] = str(writer.path)
            self.current = None
            self._emit("on_finished", dataset)
        return dataset
