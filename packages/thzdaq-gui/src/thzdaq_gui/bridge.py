"""The bench's events as Qt signals. A lab tells its events in its own thread
(a lane, the event stream); the bridge hands each to the GUI thread and emits
it on the signal of its kind, where view models take it."""

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_api import events
from thzdaq_api.lab import Lab


class Bridge(QObject):
    quantity_set = Signal(object)  # QuantitySet
    action_done = Signal(object)  # ActionDone
    values = Signal(object)  # Values
    read_failed = Signal(object)  # ReadFailed
    measurement_started = Signal(object)  # MeasurementStarted
    measurement_records = Signal(object)  # MeasurementRecords
    measurement_progress = Signal(object)  # MeasurementProgress
    measurement_log = Signal(object)  # MeasurementLog
    measurement_finished = Signal(object)  # MeasurementFinished
    station_changed = Signal(object)  # StationChanged
    leases_changed = Signal(object)  # LeasesChanged
    resync = Signal(object)  # Resync: events were lost, take a new snapshot
    _heard = Signal(object)  # an Event, emitted in the lab's thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop: Optional[Callable[[], None]] = None
        self._signals = {
            events.QuantitySet: self.quantity_set,
            events.ActionDone: self.action_done,
            events.Values: self.values,
            events.ReadFailed: self.read_failed,
            events.MeasurementStarted: self.measurement_started,
            events.MeasurementRecords: self.measurement_records,
            events.MeasurementProgress: self.measurement_progress,
            events.MeasurementLog: self.measurement_log,
            events.MeasurementFinished: self.measurement_finished,
            events.StationChanged: self.station_changed,
            events.LeasesChanged: self.leases_changed,
            events.Resync: self.resync,
        }
        # Emitted from another thread, delivered in this object's: the GUI's
        self._heard.connect(self._tell)

    def listen(self, lab: Lab, since: Optional[int] = None) -> None:
        """Hear this lab (and no other) after event since, from now for None."""
        self.stop()
        self._stop = lab.subscribe(self._heard.emit, since)

    def stop(self) -> None:
        if self._stop is not None:
            self._stop()
            self._stop = None

    def _tell(self, event: events.Event) -> None:
        self._signals[type(event.body)].emit(event.body)
