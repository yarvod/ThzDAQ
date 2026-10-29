import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypeVar

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_api.devices import (
    DescribeDevice,
    DeviceDescription,
    DeviceInfo,
    ListDevices,
)
from thzdaq_api.lab import Lab
from thzdaq_api.operation import Operation
from thzdaq_api.measurements import ListProcedures, ProcedureSummary
from thzdaq_api.station import (
    ConnectionKindInfo,
    DriverInfo,
    GetStation,
    ListConnectionKinds,
    ListDrivers,
    StationProfile,
    UpdateStation,
)
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
R = TypeVar("R")

# A TCP connection unused this long is closed (reopened on the next command):
# an R&S instrument stays in remote with a client connected
IDLE_CONNECTION_S = 5.0
EMPTY = "bench"  # the profile of the lab before one is loaded


class Session(QObject):
    """What the window works with: the bench profile, data and workers.

    The profile is always a file: Setup edits it and every change is saved
    at once, like the old settings.ini. An edit goes to the lab
    (update_profile); config_changed follows when the lab tells it.

    lab is the bench as the daemon's clients call it; bridge brings its events
    to the GUI thread, calls runs its operations in the background, a queue per
    instrument. Until the GUI connects to a daemon (milestone M1, step 6) the
    lab runs in this process, around the session's own station and on the
    worker's lanes, which Setup still uses to open instruments itself.
    """

    station_changed = Signal(object)  # a new Station (another profile)
    config_changed = Signal()  # the profile was edited: devices may differ

    def __init__(self, data_root: str = "data", parent=None):
        super().__init__(parent)
        self.data_root = Path(data_root)  # where measurements are written
        self.worker = DeviceWorker(self)
        # Lanes of their own: a call waits for its instrument's lane in worker
        self.calls = DeviceWorker(self)
        self.measurements = MeasurementsModel(self, self)
        # Where file dialogs start until the user picks a folder of a kind
        self.folders = Folders(
            {MEASUREMENTS: lambda: self.data_root, PROFILES: stations_dir}
        )
        self.runs: List[RunModel] = []
        self.processes = Processes(self)  # what runs now, for the Processes dock
        self.station: Optional[Station] = None
        self.lab: Optional[Lab] = None
        self.bridge = Bridge(self)
        self._assembled: Optional[Assembled] = None
        self._procedures: Optional[Tuple[ProcedureSummary, ...]] = None
        self._drivers: Optional[Dict[str, DriverInfo]] = None
        self._connection_kinds: Optional[Tuple[ConnectionKindInfo, ...]] = None
        self.bridge.station_changed.connect(self._profile_changed)
        self.path: Optional[Path] = None
        self.simulate = False
        self.lively = True  # simulators drift and get noisy (tests turn it off)
        self._open_lab(Station(StationConfig(EMPTY), pause=time.sleep), False)
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

    def call(self, operation: Operation[R]) -> R:
        """An operation of the lab now (another profile replaces the lab)."""
        return self.lab.call(operation)

    def procedures(self) -> Tuple[ProcedureSummary, ...]:
        """The procedures the bench runs, with their plots; asked once, they
        do not change."""
        if self._procedures is None:
            self._procedures = self.lab.call(ListProcedures())
        return self._procedures

    def procedure(self, name: str) -> ProcedureSummary:
        return next(p for p in self.procedures() if p.name == name)

    def drivers(self) -> Dict[str, DriverInfo]:
        """Drivers a profile may name, by key."""
        if self._drivers is None:
            self._drivers = {d.key: d for d in self.lab.call(ListDrivers())}
        return self._drivers

    def connection_kinds(self) -> Tuple[ConnectionKindInfo, ...]:
        if self._connection_kinds is None:
            self._connection_kinds = self.lab.call(ListConnectionKinds())
        return self._connection_kinds

    # What the profile gives: asked once per profile
    def profile(self) -> StationProfile:
        if self._profile is None:
            self._profile = self.lab.call(GetStation())
        return self._profile

    def update_profile(self, profile: Dict[str, Any]) -> None:
        """Hand an edited profile to the lab, which checks, saves and applies it
        (LabError when it refuses)."""
        self._profile = self.lab.call(UpdateStation(profile=profile))

    def _profile_changed(self, *_) -> None:
        self._forget_devices()
        self.config_changed.emit()

    def devices(self) -> Tuple[DeviceInfo, ...]:
        if self._devices is None:
            self._devices = self.lab.call(ListDevices())
        return self._devices

    def description(self, ref: str) -> DeviceDescription:
        """What a device reads, takes and does."""
        if ref not in self._descriptions:
            self._descriptions[ref] = self.lab.call(DescribeDevice(ref=ref))
        return self._descriptions[ref]

    def _forget_devices(self) -> None:
        self._profile: Optional[StationProfile] = None
        self._devices: Optional[Tuple[DeviceInfo, ...]] = None
        self._descriptions: Dict[str, DeviceDescription] = {}

    def busy(self) -> bool:
        return any(run.running for run in self.runs)

    def title_of(self, ref: str) -> str:
        return next((d.title for d in self.devices() if d.ref == ref), ref)

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

    def _open_lab(self, station: Station, simulate: bool) -> None:
        """The use cases around this station, in this process; the lanes are
        the worker's, so manual control and the lab take turns per instrument."""
        root = self.data_root
        path = str(self.path) if self.path is not None else None
        bench = Bench(station, self.worker.lanes, path)
        workspaces = Workspaces(root.parent, root, MeasurementStore)
        self._assembled = assemble(
            bench, workspaces, YamlProfiles(), LocalControl(simulate)
        )
        self.lab = LocalLab(self._assembled, origin="gui")
        self._forget_devices()
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
        self.calls.stop(timeout)
        self.worker.stop(timeout)
