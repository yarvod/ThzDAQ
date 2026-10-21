import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_core.data.store import DataStore
from thzdaq_core.station.station import Station

from thzdaq_gui.workers import DeviceWorker, QtRunner

logger = logging.getLogger(__name__)


class Session(QObject):
    """What the window works with: the bench, the data folder and the workers."""

    station_changed = Signal(object)  # Station or None

    def __init__(self, data_root: str = "data", parent=None):
        super().__init__(parent)
        self.store = DataStore(data_root)
        self.worker = DeviceWorker(self)
        self.runner = QtRunner(self)
        self.station: Optional[Station] = None
        self.path: Optional[Path] = None
        self.simulate = False

    def load_station(self, path, simulate: bool = False) -> Station:
        station = Station.load(path, simulate=simulate)
        self._close_station()
        self.station, self.path, self.simulate = station, Path(path), simulate
        logger.info(f"Station {station.name} loaded from {path} (simulate={simulate})")
        self.station_changed.emit(station)
        return station

    def reload(self, simulate: Optional[bool] = None) -> Optional[Station]:
        if self.path is None:
            return None
        return self.load_station(
            self.path, self.simulate if simulate is None else simulate
        )

    def _close_station(self) -> None:
        if self.station is not None:
            old = self.station
            # Closing talks to instruments: do it in the device thread, after pending jobs
            self.worker.submit(old.close)
            self.station = None

    def shutdown(self, timeout: float = 5.0) -> None:
        if self.runner.running:
            self.runner.cancel()
            self.runner.wait(timeout)
        self._close_station()
        self.worker.stop(timeout)
