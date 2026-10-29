"""Measurements running in the daemon.

Each runs in its own thread with its own runner, so measurements run side by
side; its id is the measurement's number, known as soon as it starts. Clients
follow it by events (started with the plots it fills, records a few at a time,
progress, log, finished) or by waiting on its id.
"""

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Mapping, Optional, Tuple

from thzdaq_api.data import encode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import (
    MeasurementFinished,
    MeasurementLog,
    MeasurementProgress,
    MeasurementRecords,
    MeasurementStarted,
)
from thzdaq_api.measurements import RunInfo

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import plot_info
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.ports import MeasurementRepository
from thzdaq_core.application.runner import MeasurementRunner, RunObserver
from thzdaq_core.domain.data.measurement import RUNNING, Measurement
from thzdaq_core.domain.errors import ProcedureError, StationError
from thzdaq_core.domain.measurements.procedure import Procedure

BATCH_S = 0.05  # records travel in batches of about this long
KEPT = 100  # runs that ended, remembered for ListRuns and wait


class _Run(RunObserver):
    def __init__(self, procedure: Procedure, origin: str, events: EventBus):
        self.procedure = procedure
        self.origin = origin
        self.events = events
        self.runner: Optional[MeasurementRunner] = None
        self.measurement: Optional[Measurement] = None
        self.refused: Optional[LabError] = None  # failed before it started
        self.started: Optional[RunInfo] = None  # as it started
        self.ready = threading.Event()  # started, or refused
        self.ended = threading.Event()
        self.done, self.total = 0, procedure.estimate_steps()
        self._batch: Dict[str, List[Dict[str, Any]]] = {}
        self._flushed = time.monotonic()

    def info(self) -> RunInfo:
        m = self.measurement
        return RunInfo(
            id=m.id,
            procedure=m.procedure,
            title=m.title,
            status=m.status,
            devices={slot: use.ref for slot, use in m.devices.items()},
            origin=self.origin,
            comment=m.comment,
            done=self.done,
            total=self.total,
            started=m.started,
            finished=m.finished,
            error=m.error,
            path=m.metadata.get("path"),
        )

    def execute(self, bench: Bench, comment: str, devices: Mapping[str, str]) -> None:
        try:
            self.runner.run(self.procedure, comment, devices)
        except (ProcedureError, StationError) as e:
            self.refused = LabError(ErrorCode.INVALID_ARGUMENTS, str(e))
        except Exception as e:  # the store or the station failed before the start
            self.refused = LabError(ErrorCode.INTERNAL, f"not started: {e}")
        finally:
            self.ready.set()
            self.ended.set()

    # RunObserver: what the runner tells, as events
    def on_started(self, measurement: Measurement) -> None:
        self.measurement = measurement
        station = self.runner.station
        refs = {slot: use.ref for slot, use in measurement.devices.items()}
        plots = self.procedure.active_plots(lambda slot: station.quantities(refs[slot]))
        self.started = self.info()
        self.events.publish(
            MeasurementStarted(self.started, tuple(plot_info(p) for p in plots))
        )
        self.ready.set()

    def on_record(self, table: str, record: Dict[str, Any]) -> None:
        self._batch.setdefault(table, []).append(encode_values(record))
        if time.monotonic() - self._flushed >= BATCH_S:
            self._flush()

    def on_progress(self, done: int, total: Optional[int]) -> None:
        self._flush()
        self.done, self.total = done, total
        self.events.publish(MeasurementProgress(self.measurement.id, done, total))

    def on_log(self, message: str) -> None:
        self._flush()
        self.events.publish(MeasurementLog(self.measurement.id, message))

    def on_finished(self, measurement: Measurement) -> None:
        self._flush()
        self.events.publish(MeasurementFinished(self.info()))

    def _flush(self) -> None:
        batch, self._batch = self._batch, {}
        self._flushed = time.monotonic()
        for table, rows in batch.items():
            self.events.publish(
                MeasurementRecords(self.measurement.id, table, tuple(rows))
            )


class Runs:
    def __init__(self, bench: Bench, store: MeasurementRepository, events: EventBus):
        self.bench = bench
        self.store = store
        self.events = events
        self._runs: "OrderedDict[int, _Run]" = OrderedDict()
        self._lock = threading.Lock()

    def start(
        self,
        procedure: Procedure,
        devices: Mapping[str, str],
        comment: str,
        origin: str,
    ) -> RunInfo:
        run = _Run(procedure, origin, self.events)
        run.runner = MeasurementRunner(self.bench.station, self.store, [run])
        threading.Thread(
            target=run.execute,
            args=(self.bench, comment, dict(devices)),
            name=f"run {procedure.name}",
            daemon=True,
        ).start()
        run.ready.wait()
        if run.refused is not None:
            raise run.refused
        with self._lock:
            self._runs[run.measurement.id] = run
            self._forget_old()
        return run.started

    def _run(self, run_id: int) -> _Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise LabError(
                ErrorCode.NOT_FOUND, f"No measurement {run_id} in the daemon"
            )
        return run

    def _forget_old(self) -> None:
        ended = [i for i, r in self._runs.items() if r.ended.is_set()]
        for run_id in ended[: max(0, len(ended) - KEPT)]:
            del self._runs[run_id]

    def active(self) -> Tuple[RunInfo, ...]:
        """The runs that have not ended."""
        return tuple(info for info in self.all() if info.status == RUNNING)

    def get(self, run_id: int) -> RunInfo:
        return self._run(run_id).info()

    def all(self) -> Tuple[RunInfo, ...]:
        with self._lock:
            runs = list(self._runs.values())
        return tuple(run.info() for run in runs)

    def wait(self, run_id: int, timeout: float) -> RunInfo:
        run = self._run(run_id)
        run.ended.wait(timeout)
        return run.info()

    def cancel(self, run_id: int) -> RunInfo:
        run = self._run(run_id)
        run.runner.cancel()
        return run.info()

    def abort(self, run_id: int) -> RunInfo:
        """Cancel, and break the connections of its devices: a read that hangs
        ends at once (the connections reopen on the next command)."""
        run = self._run(run_id)
        run.runner.cancel()
        if run.measurement.status == RUNNING:
            self.bench.station.abort(run.info().devices.values())
        return run.info()

    def stop(self, timeout: float = 5.0) -> None:
        """Cancel every run and wait for them to restore what they changed."""
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.runner.cancel()
        deadline = time.monotonic() + timeout
        for run in runs:
            run.ended.wait(max(0.0, deadline - time.monotonic()))
