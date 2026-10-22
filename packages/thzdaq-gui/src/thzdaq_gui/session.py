import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_core.data.store import MeasurementStore
from thzdaq_core.station.config import StationConfig
from thzdaq_core.station.station import Station
from thzdaq_core.station.storage import load_station, save_station

from thzdaq_gui.measurements import MeasurementsModel
from thzdaq_gui.workers import DeviceWorker, QtRunner

logger = logging.getLogger(__name__)


class Session(QObject):
    """What the window works with: the bench profile, data and workers.

    The profile is always a file: Setup edits it and every change is saved
    at once, like the old settings.ini.
    """

    station_changed = Signal(object)  # a new Station (another profile)
    config_changed = Signal(object)  # the same Station with an edited profile

    def __init__(self, data_root: str = "data", parent=None):
        super().__init__(parent)
        self.store = MeasurementStore(data_root)
        self.worker = DeviceWorker(self)
        self.measurements = MeasurementsModel(self.store, self)
        self.runners: List[QtRunner] = []
        self.station: Optional[Station] = None
        self.path: Optional[Path] = None
        self.simulate = False

    def runner(self) -> QtRunner:
        """A runner for one dock; stopped on shutdown."""
        runner = QtRunner(self)
        runner.started.connect(self.measurements.add)
        runner.finished.connect(self.measurements.refresh_item)
        self.runners.append(runner)
        return runner

    def busy(self) -> bool:
        return any(runner.running for runner in self.runners)

    def load_station(self, path, simulate: bool = False) -> Station:
        station = Station(load_station(path), simulate=simulate)
        self._close_station()
        self.station, self.path, self.simulate = station, Path(path), simulate
        logger.info(f"Station {station.name} loaded from {path} (simulate={simulate})")
        self.station_changed.emit(station)
        return station

    def new_station(self, path, name: str = "bench") -> Station:
        save_station(StationConfig(name), path)
        return self.load_station(path, self.simulate)

    def reload(self, simulate: Optional[bool] = None) -> Optional[Station]:
        if self.path is None:
            return None
        return self.load_station(
            self.path, self.simulate if simulate is None else simulate
        )

    def update_config(self, config: StationConfig) -> None:
        """Apply an edited profile: save the file, reopen changed instruments."""
        config.validate()
        if self.station is None:
            raise RuntimeError("No station loaded")
        if self.path is not None:
            save_station(config, self.path)
        # Only closes instruments whose connection changed; they reopen on next use
        self.station.reconfigure(config)
        self.config_changed.emit(self.station)

    def _close_station(self) -> None:
        if self.station is not None:
            old = self.station
            self.worker.submit(old.close)
            self.station = None

    def shutdown(self, timeout: float = 5.0) -> None:
        for runner in self.runners:
            if runner.running:
                runner.cancel()
                runner.wait(timeout)
        self._close_station()
        self.worker.stop(timeout)
