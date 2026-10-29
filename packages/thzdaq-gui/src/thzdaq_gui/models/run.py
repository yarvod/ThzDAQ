"""A measurement as a procedure box runs it: started through the lab, followed by
its events, its records gathered into a measurement as they come.

The start is an operation in the background (it opens the instruments); the
events of the run may come before its answer, so they wait until the run's
number is known. A start refused because a device it needs is swept by another
measurement is a conflict: whoever drives the run asks, and share() goes on.
"""

from typing import Any, Callable, Dict, List, Mapping, Optional

import msgspec
from PySide6.QtCore import QObject, Signal
from thzdaq_api import events
from thzdaq_api.data import decode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import CONFLICTS, RUNNING, DeviceUse, Measurement
from thzdaq_api.measurements import (
    AbortMeasurement,
    CancelMeasurement,
    RunInfo,
    StartMeasurement,
)

Body = Any  # a measurement event's body


def run_of(body: Body) -> int:
    """The number of the run an event tells about."""
    run = getattr(body, "run", None)
    return run.id if run is not None else body.id


class RunModel(QObject):
    started = Signal(object)  # Measurement, filled as records come
    record = Signal(str, object)  # table, record
    progress = Signal(int, object)  # done, total or None
    log = Signal(str)
    finished = Signal(object)  # Measurement, ended
    failed = Signal(str)  # could not start: missing device, bad parameters
    conflict = Signal(str)  # could not start: another measurement sweeps a device
    running_changed = Signal(bool)

    def __init__(self, session, title_of: Callable[[str], str], parent=None):
        """title_of(ref): how a device is named in the curves of the run."""
        super().__init__(parent)
        self.session = session
        self.title_of = title_of
        self.run: Optional[RunInfo] = None
        self._asked: Optional[StartMeasurement] = None  # the last start
        self.measurement: Optional[Measurement] = None
        self.running = False
        self._early: List[Body] = []  # events heard before the run's number
        bridge = session.bridge
        self._handlers = {
            events.MeasurementStarted: self._on_started,
            events.MeasurementRecords: self._on_records,
            events.MeasurementProgress: self._on_progress,
            events.MeasurementLog: self._on_log,
            events.MeasurementFinished: self._on_finished,
        }
        for signal in (
            bridge.measurement_started,
            bridge.measurement_records,
            bridge.measurement_progress,
            bridge.measurement_log,
            bridge.measurement_finished,
        ):
            signal.connect(self._heard)

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
            workspace=str(self.session.workspace),
        )

    def _start(self, operation: StartMeasurement) -> None:
        if self.running:
            raise RuntimeError("A measurement is already running")
        self.run, self.measurement, self._early = None, None, []
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
        early, self._early = self._early, []
        for body in early:
            self._heard(body)

    def _refused(self, error: BaseException) -> None:
        self._set_running(False)
        if isinstance(error, LabError) and error.code == ErrorCode.CONFLICT:
            self.conflict.emit(str(error))
        else:
            self.failed.emit(str(error))

    def _heard(self, body: Body) -> None:
        if self.run is None:
            if self.running:
                self._early.append(body)
            return
        if run_of(body) == self.run.id:
            self._handlers[type(body)](body)

    def _on_started(self, body: events.MeasurementStarted) -> None:
        run = body.run
        self.measurement = Measurement(
            procedure=run.procedure,
            title=run.title,
            id=run.id,
            status=RUNNING,
            started=run.started,
            comment=run.comment,
            devices={
                slot: DeviceUse(ref, self.title_of(ref))
                for slot, ref in run.devices.items()
            },
            metadata={"path": run.path} if run.path else {},
        )
        self._noted(run)
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

    def _on_finished(self, body: events.MeasurementFinished) -> None:
        run = body.run
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
