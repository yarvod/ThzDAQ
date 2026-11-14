"""A measurement started here or observed in the lab, followed by events.

RunEvents routes events after the run's number is known; this model gathers
records and exposes the same state for local and external starts.
A start refused because a device it needs is swept by another
measurement is a conflict: whoever drives the run asks, and share() goes on.
"""

from typing import Any, Callable, Dict, Mapping, Optional

import msgspec
from PySide6.QtCore import QObject, Signal
from thzdaq_api import events
from thzdaq_api.data import decode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import (
    CONFLICTS,
    INTERRUPTED,
    RUNNING,
    DeviceUse,
    Measurement,
)
from thzdaq_api.measurements import (
    AbortMeasurement,
    CancelMeasurement,
    RunInfo,
    RunSnapshot,
    StartMeasurement,
)


def measurement_of(run: RunInfo, title_of: Callable[[str], str]) -> Measurement:
    """A run as a measurement without its records (they come by events, or
    from its file); the conflicts it accepted as its file keeps them."""
    metadata: Dict[str, Any] = {"path": run.path} if run.path else {}
    if run.conflicts:
        metadata[CONFLICTS] = list(run.conflicts)
    return Measurement(
        procedure=run.procedure,
        title=run.title,
        id=run.id,
        status=run.status,
        started=run.started,
        finished=run.finished,
        error=run.error,
        comment=run.comment,
        devices={
            slot: DeviceUse(ref, title_of(ref)) for slot, ref in run.devices.items()
        },
        metadata=metadata,
    )


class RunModel(QObject):
    started = Signal(object)  # Measurement, filled as records come
    record = Signal(str, object)  # table, record
    progress = Signal(int, object)  # done, total or None
    log = Signal(str)
    plotted = Signal(object)  # PlotInfo: drawn from now on (a script's plot)
    finished = Signal(object)  # Measurement, ended
    failed = Signal(str)  # could not start: missing device, bad parameters
    conflict = Signal(str)  # could not start: another measurement sweeps a device
    running_changed = Signal(bool)
    resetting = Signal(object)  # Measurement: its records will be replaced

    def __init__(self, session, title_of: Callable[[str], str], parent=None):
        """session: what starts and stops its runs, None where a run is only
        watched (the plots window); title_of(ref): how a device is named in
        the curves of the run."""
        super().__init__(parent)
        self.session = session
        self.title_of = title_of
        self.run: Optional[RunInfo] = None
        self._asked: Optional[StartMeasurement] = None  # the last start
        self.measurement: Optional[Measurement] = None
        self.running = False
        self.plots = ()
        self.seq = 0
        self._handlers = {
            events.MeasurementStarted: self._on_started,
            events.MeasurementRecords: self._on_records,
            events.MeasurementProgress: self._on_progress,
            events.MeasurementLog: self._on_log,
            events.MeasurementPlotted: self._on_plotted,
            events.MeasurementFinished: self._on_finished,
        }

    def start(
        self,
        procedure: str,
        parameters: Mapping[str, Any],
        devices: Mapping[str, str],
        comment: str = "",
    ) -> None:
        self._start(self._operation(procedure, parameters, devices, comment))

    def share(self) -> None:
        """Start the run refused for a conflict again, the conflict accepted:
        both measurements note it."""
        self._start(msgspec.structs.replace(self._asked, share=True))

    def check(
        self, procedure: str, parameters: Mapping[str, Any], devices: Mapping[str, str]
    ) -> RunInfo:
        """The run a start would make, checked by the lab without starting it
        (a dry run); LabError says why it would not start."""
        operation = self._operation(procedure, parameters, devices)
        return self.session.call(msgspec.structs.replace(operation, dry_run=True))

    def _operation(
        self,
        procedure: str,
        parameters: Mapping[str, Any],
        devices: Mapping[str, str],
        comment: str = "",
    ) -> StartMeasurement:
        return StartMeasurement(
            procedure=procedure,
            parameters=dict(parameters),
            devices=dict(devices),
            comment=comment,
            workspace=str(self.session.workspace.folder),
        )

    def _start(self, operation: StartMeasurement) -> None:
        if self.running:
            raise RuntimeError("A measurement is already running")
        self.run, self.measurement, self.seq = None, None, 0
        self._asked = operation
        self._set_running(True)
        lab = self.session.lab
        self.session.calls.submit(
            lambda: lab.call(operation), self._accepted, self._refused
        )

    def cancel(self) -> None:
        self._call(CancelMeasurement)

    def abort(self) -> None:
        """Cancel, and break the connections of its devices: a read that hangs
        ends at once."""
        self._call(AbortMeasurement)

    def _call(self, operation) -> None:
        if self.run is not None and self.running:
            lab, call = self.session.lab, operation(id=self.run.id)
            self.session.calls.submit(lambda: lab.call(call))

    def _accepted(self, run: RunInfo) -> None:
        self.run = run
        self.session.run_events.claim(self)

    def _refused(self, error: BaseException) -> None:
        self._set_running(False)
        self.session.run_events.release()
        if isinstance(error, LabError) and error.code == ErrorCode.CONFLICT:
            self.conflict.emit(str(error))
        else:
            self.failed.emit(str(error))

    def hear(self, event: events.Event) -> None:
        if event.seq > self.seq:
            self.seq = event.seq
            self._handlers[type(event.body)](event.body)

    def restore(self, snapshot: RunSnapshot) -> None:
        """Replace with a coherent snapshot, then accept only newer events."""
        self.seq = snapshot.seq
        self.run = snapshot.run
        if self.measurement is None:
            self._on_started(events.MeasurementStarted(snapshot.run, snapshot.plots))
        else:
            self.resetting.emit(self.measurement)
            self.measurement.tables.clear()
            self.plots = snapshot.plots
        for table, rows in snapshot.rows.items():
            self._on_records(events.MeasurementRecords(snapshot.run.id, table, rows))
        self._on_progress(
            events.MeasurementProgress(
                snapshot.run.id, snapshot.run.done, snapshot.run.total
            )
        )
        if snapshot.run.status != RUNNING:
            self._on_finished(events.MeasurementFinished(snapshot.run))

    def detach(self) -> None:
        """Stop following this lab; its measurement keeps running there."""
        self.run = None
        self._set_running(False)

    def lost(self) -> None:
        """The reconnected daemon no longer has the run we were following."""
        if self.running and self.measurement is not None:
            run = msgspec.structs.replace(self.run, status=INTERRUPTED)
            self._on_finished(events.MeasurementFinished(run))

    def _on_started(self, body: events.MeasurementStarted) -> None:
        run = body.run
        self.run = run
        self.plots = body.plots
        self._set_running(True)
        self.measurement = measurement_of(run, self.title_of)
        self.measurement.status = RUNNING
        self.started.emit(self.measurement)

    def _on_records(self, body: events.MeasurementRecords) -> None:
        for row in body.rows:
            record: Dict[str, Any] = decode_values(row)
            self.measurement.append(body.table, record)
            self.record.emit(body.table, record)

    def _on_progress(self, body: events.MeasurementProgress) -> None:
        self.progress.emit(body.done, body.total)

    def _on_log(self, body: events.MeasurementLog) -> None:
        self.log.emit(body.message)

    def _on_plotted(self, body: events.MeasurementPlotted) -> None:
        self.plots += (body.plot,)
        self.plotted.emit(body.plot)

    def _on_finished(self, body: events.MeasurementFinished) -> None:
        run = body.run
        self.run = run
        measurement = self.measurement
        measurement.finish(run.status, run.finished or "", run.error)
        if run.path:
            measurement.metadata["path"] = run.path
        self._noted(run)
        self.finished.emit(measurement)
        self._set_running(False)

    def _noted(self, run: RunInfo) -> None:
        """The conflicts it accepted, as its file keeps them: Data marks it."""
        if run.conflicts:
            self.measurement.metadata[CONFLICTS] = list(run.conflicts)

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.running_changed.emit(running)
