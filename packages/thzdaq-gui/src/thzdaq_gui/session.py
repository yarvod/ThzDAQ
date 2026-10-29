import logging
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_api.lab import Lab
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station, save_station
from thzdaq_core.application.assembly import Assembled, assemble
from thzdaq_core.application.bench import Bench
from thzdaq_core.application.local import LocalControl, LocalLab
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_core.domain.station.config import StationConfig
from thzdaq_core.domain.station.station import Station

from thzdaq_gui.bridge import Bridge
from thzdaq_gui.folders import MEASUREMENTS, PROFILES, Folders
from thzdaq_gui.measurements import MeasurementsModel
from thzdaq_gui.processes import Processes
from thzdaq_gui.settings import stations_dir
from thzdaq_gui.models.run import RunModel
from thzdaq_gui.workers import DeviceWorker

logger = logging.getLogger(__name__)

# A TCP connection unused this long is closed (reopened on the next command):
# an R&S instrument stays in remote with a client connected
IDLE_CONNECTION_S = 5.0


class Session(QObject):
    """What the window works with: the bench profile, data and workers.

    The profile is always a file: Setup edits it and every change is saved
    at once, like the old settings.ini.

    lab is the bench as the daemon's clients call it; bridge brings its events
    to the GUI thread. Until the GUI connects to a daemon (milestone M1, step
    6) the lab runs in this process, around the session's own station, so the
    instruments still have one owner while the docks move onto it.
    """

    station_changed = Signal(object)  # a new Station (another profile)
    config_changed = Signal(object)  # the same Station with an edited profile

    def __init__(self, data_root: str = "data", parent=None):
        super().__init__(parent)
        self.store = MeasurementStore(data_root)
        self.worker = DeviceWorker(self)
        self.measurements = MeasurementsModel(self.store, self)
        # Where file dialogs start until the user picks a folder of a kind
        self.folders = Folders(
            {MEASUREMENTS: lambda: self.store.root, PROFILES: stations_dir}
        )
        self.runs: List[RunModel] = []
        self.processes = Processes(self)  # what runs now, for the Processes dock
        self.station: Optional[Station] = None
        self.lab: Optional[Lab] = None
        self.bridge = Bridge(self)
        self._assembled: Optional[Assembled] = None
        self.path: Optional[Path] = None
        self.simulate = False
        self.lively = True  # simulators drift and get noisy (tests turn it off)
        self.idleTimer = QTimer(self)
        self.idleTimer.timeout.connect(self.close_idle_connections)
        self.idleTimer.start(1000)

    def close_idle_connections(self) -> None:
        if self.station is not None:
            self.station.close_idle_connections(IDLE_CONNECTION_S)

    def run_model(self) -> RunModel:
        """The runs of one procedure box; Data lists what they measure."""
        run = RunModel(self, self.title_of, self)
        run.started.connect(self.measurements.add)
        run.finished.connect(self.measurements.refresh_item)
        self.runs.append(run)
        return run

    def busy(self) -> bool:
        return any(run.running for run in self.runs)

    def title_of(self, ref: str) -> str:
        return self.station.title(ref) if self.station is not None else ref

    def load_station(self, path, simulate: bool = False) -> Station:
        station = Station(
            load_station(path), pause=time.sleep, simulate=simulate, lively=self.lively
        )
        self._close_station()
        self.station, self.path, self.simulate = station, Path(path), simulate
        self._open_lab(station, simulate)
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

    def _open_lab(self, station: Station, simulate: bool) -> None:
        """The use cases around this station, in this process; the lanes are
        the worker's, so manual control and the lab take turns per instrument."""
        root = Path(self.store.root)
        bench = Bench(station, self.worker.lanes, str(self.path))
        workspaces = Workspaces(root.parent, root, MeasurementStore)
        self._assembled = assemble(
            bench, workspaces, YamlProfiles(), LocalControl(simulate)
        )
        self.lab = LocalLab(self._assembled, origin="gui")
        self.bridge.listen(self.lab)

    def _close_station(self) -> None:
        if self._assembled is not None:
            self.bridge.stop()
            self._assembled.close()
            self._assembled, self.lab = None, None
        if self.station is not None:
            old = self.station
            self.worker.submit(old.close)
            self.station = None

    def shutdown(self, timeout: float = 5.0) -> None:
        # Closing the lab cancels its runs and waits for their on_exit
        self._close_station()
        self.worker.stop(timeout)
