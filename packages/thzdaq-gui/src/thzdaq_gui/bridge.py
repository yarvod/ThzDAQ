"""The bench's events as Qt signals. A lab tells its events in its own thread
(a lane, the event stream); the bridge hands each to the GUI thread and emits
it on the signal of its kind, where view models take it."""

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from thzdaq_api import events
from thzdaq_api.lab import Lab


class Bridge(QObject):
    measurement_event = Signal(object)  # numbered Event, for run catch-up
    quantity_set = Signal(object)  # QuantitySet
    action_done = Signal(object)  # ActionDone
    raw_sent = Signal(object)  # RawSent
    script_started = Signal(object)  # ScriptStarted
    script_output = Signal(object)  # ScriptOutput
    script_ended = Signal(object)  # ScriptEnded
    procedures_changed = Signal(object)  # ProceduresChanged
    values = Signal(object)  # Values
    read_failed = Signal(object)  # ReadFailed
    station_changed = Signal(object)  # StationChanged
    leases_changed = Signal(object)  # LeasesChanged
    approval_requested = Signal(object)  # ApprovalRequested
    approval_answered = Signal(object)  # ApprovalAnswered
    ui_requested = Signal(object)  # UiRequested: of some window, maybe this one
    resync = Signal(object)  # Resync: events were lost, take a new snapshot
    _heard = Signal(int, object)  # subscription generation, Event

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop: Optional[Callable[[], None]] = None
        self._generation = 0
        self._signals = {
            events.QuantitySet: self.quantity_set,
            events.ActionDone: self.action_done,
            events.RawSent: self.raw_sent,
            events.ScriptStarted: self.script_started,
            events.ScriptOutput: self.script_output,
            events.ScriptEnded: self.script_ended,
            events.ProceduresChanged: self.procedures_changed,
            events.Values: self.values,
            events.ReadFailed: self.read_failed,
            events.StationChanged: self.station_changed,
            events.LeasesChanged: self.leases_changed,
            events.ApprovalRequested: self.approval_requested,
            events.ApprovalAnswered: self.approval_answered,
            events.UiRequested: self.ui_requested,
            events.Resync: self.resync,
        }
        # Delivered in this object's thread (the GUI's) through its event queue,
        # also when emitted there (a LocalLab called from the GUI thread): Qt
        # would call a same-thread slot at once, ahead of events of other
        # threads already queued, and the order of the events would break
        self._heard.connect(self._tell, Qt.ConnectionType.QueuedConnection)

    def listen(self, lab: Lab, since: Optional[int] = None) -> None:
        """Hear this lab (and no other) after event since, from now for None."""
        self.stop()
        generation = self._generation
        self._stop = lab.subscribe(
            lambda event: self._heard.emit(generation, event), since
        )

    def stop(self) -> None:
        self._generation += 1
        if self._stop is not None:
            self._stop()
            self._stop = None

    def _tell(self, generation: int, event: events.Event) -> None:
        if generation != self._generation:
            return
        if events.run_id(event.body) is not None:
            self.measurement_event.emit(event)
        else:
            self._signals[type(event.body)].emit(event.body)
