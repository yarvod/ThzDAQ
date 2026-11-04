"""Measurements running in the daemon.

Each runs in its own thread with its own runner, so measurements run side by
side; its id is the measurement's number, given before it starts. It takes
leases on its devices first (thzdaq_core.domain.leases): a conflict without
share refuses the start, one accepted is noted in both measurements. Clients
follow a run by events (started with the plots it fills, records a few at a
time, progress, log, finished) or by waiting on its id. What a run sets its
devices to is told as quantity_set, at most SET_EVERY_S apart per quantity
(a value held back goes with the next progress or record, the last ones when
the run ends), so a sweep of thousands of points stays a few events a second;
the snapshot knows it too.
"""

import threading
import time
from collections import OrderedDict
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Tuple

from thzdaq_api.data import encode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import (
    LeasesChanged,
    QuantitySet,
    MeasurementFinished,
    MeasurementLog,
    MeasurementPlotted,
    MeasurementProgress,
    MeasurementRecords,
    MeasurementStarted,
)
from thzdaq_api.leases import EXCLUSIVE, READ, SHARED, LeaseInfo
from thzdaq_api.measurements import (
    PLANNED,
    MeasurementSummary,
    PlotInfo,
    RunInfo,
    RunSnapshot,
)

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.describe import measurement_summary, table_summary
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.runner import MeasurementRunner, RunObserver, slot_devices
from thzdaq_core.application.values import KnownValues
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_api.measurement_file import CONFLICTS, RUNNING, Measurement
from thzdaq_core.domain.errors import ProcedureError, StationError
from thzdaq_core.domain.leases import Lease, LeaseConflict, Leases
from thzdaq_core.domain.measurements.procedure import Procedure

BATCH_S = 0.05  # records travel in batches of about this long
SET_EVERY_S = 0.1  # what a run sets is told at most this often per quantity
KEPT = 100  # runs that ended, remembered for ListRuns and wait
STRENGTH = (READ, SHARED, EXCLUSIVE)  # a device in two slots: the stronger use


class _Run(RunObserver):
    def __init__(
        self,
        run_id: int,
        procedure: Procedure,
        origin: str,
        events: EventBus,
        known: KnownValues,
        accepted: Tuple[Lease, ...],
        ended: Callable[["_Run"], None],
        workspace: Path,
        shared: Collection[str] = (),
    ):
        self.id = run_id
        self.procedure = procedure
        self.origin = origin
        self.workspace = workspace
        self.events = events
        self.known = known
        self.accepted = accepted  # conflicts started with (share)
        self.shared = set(shared)  # devices it shares while another sweeps them
        self._ended = ended
        self.runner: Optional[MeasurementRunner] = None
        self.measurement: Optional[Measurement] = None
        self.refused: Optional[LabError] = None  # failed before it started
        self.started: Optional[RunInfo] = None  # as it started
        self.ready = threading.Event()  # started, or refused
        self.ended = threading.Event()
        # Its end is told once its file holds it: until then it runs
        self.final = False
        self.done, self.total = 0, procedure.estimate_steps()
        self._batch: Dict[str, List[Dict[str, Any]]] = {}
        self._flushed = time.monotonic()
        # What the run set and has not told yet, and when each was last told
        self._unset: Dict[Tuple[str, str], float] = {}
        self._told: Dict[Tuple[str, str], float] = {}
        # Published rows and state share a boundary with the event stream.
        self._snapshot_lock = threading.RLock()
        self._published: Dict[str, int] = {}
        self._visible: Optional[RunInfo] = None
        self._plots = ()
        self._seq = 0

    def snapshot(self) -> RunSnapshot:
        with self._snapshot_lock:
            rows = {
                table: tuple(
                    encode_values(row)
                    for row in islice(self.measurement.tables[table].rows(), count)
                )
                for table, count in self._published.items()
            }
            return RunSnapshot(self._visible, self._plots, rows, self._seq)

    def summary(self) -> MeasurementSummary:
        """What it published so far, without the arrays."""
        with self._snapshot_lock:
            tables = tuple(
                table_summary(self.measurement.tables[table], count)
                for table, count in self._published.items()
            )
        return measurement_summary(self.info(), tables, self.measurement.results)

    def _publish(self, body) -> None:
        self._seq = self.events.publish(body).seq

    def info(self) -> RunInfo:
        m = self.measurement
        return RunInfo(
            id=m.id,
            procedure=m.procedure,
            title=m.title,
            status=m.status if self.final else RUNNING,
            devices={slot: use.ref for slot, use in m.devices.items()},
            origin=self.origin,
            comment=m.comment,
            done=self.done,
            total=self.total,
            started=m.started,
            finished=m.finished if self.final else None,
            error=m.error if self.final else None,
            path=m.metadata.get("path"),
            workspace=str(self.workspace),
            conflicts=tuple(m.metadata.get(CONFLICTS, ())),
        )

    def execute(self, bench: Bench, comment: str, devices: Mapping[str, str]) -> None:
        try:
            self.runner.run(self.procedure, comment, devices, self.id)
        except (ProcedureError, StationError) as e:
            self.refused = LabError(ErrorCode.INVALID_ARGUMENTS, str(e))
        except Exception as e:  # the store or the station failed before the start
            self.refused = LabError(ErrorCode.INTERNAL, f"not started: {e}")
        finally:
            self._ended(self)
            self.ready.set()
            self.ended.set()

    # RunObserver: what the runner tells, as events
    def on_started(self, measurement: Measurement) -> None:
        self.measurement = measurement
        for lease in self.accepted:
            self.note(CONFLICTS, conflict(lease, self.origin))
        station = self.runner.station
        refs = {slot: use.ref for slot, use in measurement.devices.items()}
        plots = self.procedure.active_plots(lambda slot: station.quantities(refs[slot]))
        self.started = self.info()
        with self._snapshot_lock:
            self._visible = self.started
            self._plots = tuple(plots)
            self._publish(MeasurementStarted(self.started, self._plots))
        self.ready.set()

    def on_record(self, table: str, record: Dict[str, Any]) -> None:
        self._batch.setdefault(table, []).append(encode_values(record))
        if time.monotonic() - self._flushed >= BATCH_S:
            self._flush()

    def on_flush(self) -> None:
        self._flush()

    def on_set(self, ref: str, key: str, value: float) -> None:
        self._unset[ref, key] = value
        self._tell_due()

    def _tell_due(self) -> None:
        """What was set and not told yet, where the last telling is long enough ago."""
        now = time.monotonic()
        for quantity in list(self._unset):
            if now - self._told.get(quantity, 0.0) >= SET_EVERY_S:
                self._tell(quantity)

    def _tell(self, quantity: Tuple[str, str]) -> None:
        ref, key = quantity
        value = self._unset.pop(quantity)
        self._told[quantity] = time.monotonic()
        self.known.update(ref, {key: value})
        self.events.publish(QuantitySet(ref, key, value, origin=f"#{self.id}"))

    def on_progress(self, done: int, total: Optional[int]) -> None:
        with self._snapshot_lock:
            self._flush()
            self.done, self.total = done, total
            self._visible = self.info()
            self._publish(MeasurementProgress(self.measurement.id, done, total))

    def on_log(self, message: str) -> None:
        self._flush()
        self.events.publish(MeasurementLog(self.measurement.id, message))

    def on_plot(self, plot: PlotInfo) -> None:
        with self._snapshot_lock:
            self._flush()
            self._plots += (plot,)
            self._publish(MeasurementPlotted(self.id, plot))

    def on_finished(self, measurement: Measurement) -> None:
        for quantity in list(self._unset):
            self._tell(quantity)  # the last values, however recent
        self.final = True
        with self._snapshot_lock:
            self._flush()
            self._visible = self.info()
            self._publish(MeasurementFinished(self._visible))

    def note(self, key: str, entry: Dict[str, Any]) -> None:
        """Into the measurement's metadata (saved with it): conflicts, interactions."""
        if self.measurement is not None:
            self.measurement.metadata.setdefault(key, []).append(entry)

    def _flush(self) -> None:
        self._tell_due()
        with self._snapshot_lock:
            batch, self._batch = self._batch, {}
            self._flushed = time.monotonic()
            for table, rows in batch.items():
                self._published[table] = self._published.get(table, 0) + len(rows)
                self._publish(
                    MeasurementRecords(self.measurement.id, table, tuple(rows))
                )


def conflicting(error: LeaseConflict) -> LabError:
    return LabError(
        ErrorCode.CONFLICT,
        str(error),
        "start with share to go on: both measurements note it",
    )


def conflict(lease: Lease, by: str) -> Dict[str, Any]:
    """A conflict accepted with share, as both measurements note it."""
    return {
        "at": wall_time(),
        "by": by,
        "device": lease.device,
        "run": lease.owner,
        "mode": lease.mode,
    }


class Runs:
    def __init__(
        self,
        bench: Bench,
        workspaces: Workspaces,
        events: EventBus,
        leases: Leases,
        known: KnownValues,
    ):
        self.bench = bench
        self.workspaces = workspaces
        self.events = events
        self.leases = leases
        self.known = known
        self._runs: "OrderedDict[int, _Run]" = OrderedDict()
        self._lock = threading.Lock()
        self._last_id = 0

    def start(
        self,
        procedure: Procedure,
        devices: Mapping[str, str],
        comment: str,
        origin: str,
        share: bool = False,
        workspace: Optional[str] = None,
        dry_run: bool = False,
        shares: Collection[str] = (),
    ) -> RunInfo:
        """share: every device it uses may be swept by another measurement too,
        shares: these devices may. dry_run: check all a start checks, open and
        write nothing, and return the run it would be (planned, number 0)."""
        folder = self.workspaces.folder(workspace)
        try:
            procedure.validate()
            refs = slot_devices(procedure, devices)
        except ProcedureError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        modes: Dict[str, str] = {}
        for slot, device in refs.items():
            mode = procedure.slot_mode(slot)
            modes[device] = max(modes.get(device, READ), mode, key=STRENGTH.index)
        shared = tuple(modes) if share else tuple(shares)
        if dry_run:
            return self._plan(procedure, refs, modes, comment, origin, shared, folder)
        store = self.workspaces.store(folder)
        with self._lock:
            run_id = self._last_id = max(store.next_id(), self._last_id + 1)
        try:
            accepted = self.leases.acquire(run_id, procedure.title, modes, shared)
        except LeaseConflict as e:
            raise conflicting(e) from None
        self._leases_changed()
        for lease in accepted:
            self.note(lease.owner, CONFLICTS, conflict(lease, origin))
        run = _Run(
            run_id, procedure, origin, self.events, self.known, accepted,
            self._ended, folder, shared,
        )  # fmt: skip
        run.runner = MeasurementRunner(self.bench.station, store, [run])
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

    def _plan(
        self,
        procedure: Procedure,
        refs: Mapping[str, str],
        modes: Mapping[str, str],
        comment: str,
        origin: str,
        shared: Collection[str],
        folder: Path,
    ) -> RunInfo:
        """The run a start would make, checked without opening anything."""
        try:
            self.bench.station.check(refs, procedure.slots(), procedure.planned())
        except StationError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        refused = [c for c in self.leases.clashes(0, modes) if c.device not in shared]
        if refused:
            raise conflicting(LeaseConflict(tuple(refused)))
        return RunInfo(
            id=0,
            procedure=procedure.name,
            title=procedure.title,
            status=PLANNED,
            devices=dict(refs),
            origin=origin,
            comment=comment,
            total=procedure.estimate_steps(),
            workspace=str(folder),
        )

    def join(self, run_id: int, ref: str, mode: str, share: bool = False) -> None:
        """A device a running measurement starts using (a script's session
        reads or sets one it did not name): its lease, the stronger use when
        it has one; a conflict without share is refused, one with share is
        noted in both measurements."""
        run = self._run(run_id)
        modes = self.leases.held(run_id)
        modes[ref] = max(modes.get(ref, READ), mode, key=STRENGTH.index)
        if share:
            run.shared.add(ref)
        try:
            accepted = self.leases.acquire(
                run_id, run.procedure.title, modes, run.shared
            )
        except LeaseConflict as e:
            raise conflicting(e) from None
        for lease in accepted:
            if lease.device == ref:
                run.note(CONFLICTS, conflict(lease, run.origin))
                self.note(lease.owner, CONFLICTS, conflict(lease, run.origin))
        self._leases_changed()

    def note(self, run_id: int, key: str, entry: Dict[str, Any]) -> None:
        """Note in a running measurement's metadata (what others did to its
        devices)."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            run.note(key, entry)

    def set_comment(self, path: str, comment: str) -> None:
        """A running measurement keeps it and saves it with its data; the file
        of one that ended is written with it."""
        with self._lock:
            running = [
                run
                for run in self._runs.values()
                if not run.ended.is_set()
                and run.measurement.metadata.get("path") == path
            ]
        if running:
            running[0].measurement.comment = comment
            return
        store = self.workspaces.store(self.workspaces.home)
        try:
            measurement = store.load(path)
        except ValueError as e:
            raise LabError(ErrorCode.NOT_FOUND, str(e)) from None
        measurement.comment = comment
        store.save(measurement, path)

    def leases_now(self) -> Tuple[LeaseInfo, ...]:
        return tuple(
            LeaseInfo(lease.device, lease.mode, lease.owner, lease.title)
            for lease in self.leases.all()
        )

    def _ended(self, run: _Run) -> None:
        if self.leases.release(run.id):
            self._leases_changed()

    def _leases_changed(self) -> None:
        self.events.publish(LeasesChanged(self.leases_now()))

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

    def snapshot(self, run_id: int) -> RunSnapshot:
        return self._run(run_id).snapshot()

    def summary(self, run_id: int) -> MeasurementSummary:
        return self._run(run_id).summary()

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
