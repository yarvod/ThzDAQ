import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from PySide6.QtCore import QObject, Signal
from thzdaq_api.devices import (
    DescribeDevice,
    DeviceDescription,
    DeviceInfo,
    ListDevices,
)
from thzdaq_api.events import GetSnapshot, StationChanged
from thzdaq_api.lab import Lab
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.measurements import (
    DATA,
    ListProcedures,
    ListRuns,
    ProcedureSummary,
    RunInfo,
)
from thzdaq_api.operation import Operation
from thzdaq_api.station import (
    ConnectionKindInfo,
    DriverInfo,
    GetStation,
    ListConnectionKinds,
    ListDrivers,
    LoadStation,
    NewStation,
    StationProfile,
    UpdateStation,
)

from thzdaq_gui.bridge import Bridge
from thzdaq_gui.folders import MEASUREMENTS, PROFILES, Folders
from thzdaq_gui.measurements import MeasurementsModel
from thzdaq_gui.processes import Processes
from thzdaq_gui.settings import stations_dir
from thzdaq_gui.models.run import RunModel
from thzdaq_gui.workers import DeviceWorker

logger = logging.getLogger(__name__)
R = TypeVar("R")

# The lab of the bench, or of its simulator (simulate): a daemon to call
Connect = Callable[[bool], Lab]


class Session(QObject):
    """What the window works with: the lab, the profile it works with, the data
    of this program's workspace and the calls in the background.

    lab is the bench as the daemon's clients call it, the daemon of the
    instruments or of their simulator; bridge brings its events to the GUI
    thread, calls runs its operations in the background, a queue per
    instrument. The profile belongs to the lab: Setup edits it (update_profile),
    the File menu loads another one, and the session follows what the lab
    tells: station_changed for another profile or another lab,
    config_changed for an edited one.
    """

    station_changed = Signal()  # another profile, or another lab: build anew
    config_changed = Signal()  # the profile was edited: devices may differ

    def __init__(self, lab_of: Connect, workspace, parent=None):
        super().__init__(parent)
        # Not "connect": that name of a QObject connects its signals
        self.lab_of = lab_of
        self.workspace = Path(workspace)  # its data/ keeps this program's measurements
        self.data_root = self.workspace / DATA
        self.calls = DeviceWorker(self)
        self.measurements = MeasurementsModel(self, self)
        # Where file dialogs start until the user picks a folder of a kind
        self.folders = Folders(
            {MEASUREMENTS: lambda: self.data_root, PROFILES: stations_dir}
        )
        self.runs: List[RunModel] = []
        self.processes = Processes(self)  # what runs now, for the Processes dock
        self.lab: Optional[Lab] = None
        self.simulate = False
        self.bridge = Bridge(self)
        self.bridge.station_changed.connect(self._profile_changed)
        self.bridge.resync.connect(self._resynced)
        self._procedures: Optional[Tuple[ProcedureSummary, ...]] = None
        self._drivers: Optional[Dict[str, DriverInfo]] = None
        self._connection_kinds: Optional[Tuple[ConnectionKindInfo, ...]] = None
        self._path: Optional[str] = None  # of the profile heard last
        self._forget_devices()

    def open(self, simulate: bool) -> None:
        """Work with the lab of the instruments, or of their simulator;
        LabError when it cannot be reached."""
        lab = self.lab_of(simulate)
        self.bridge.stop()
        self.lab, self.simulate = lab, simulate
        # Events from the snapshot on: nothing between them is missed
        self.bridge.listen(lab, lab.call(GetSnapshot()).seq)
        self._forget_devices()
        self._path = self.profile().path
        logger.info(f"Working with {self._path} (simulate={simulate})")
        self.station_changed.emit()

    def run_model(self) -> RunModel:
        """The runs of one procedure box; Data lists what they measure."""
        run = RunModel(self, self.title_of, self)
        run.started.connect(self.measurements.add)
        run.finished.connect(self.measurements.refresh_item)
        self.runs.append(run)
        return run

    def call(self, operation: Operation[R]) -> R:
        """An operation of the lab now."""
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

    # The profile and what it gives: asked once per profile
    def profile(self) -> StationProfile:
        if self._profile is None:
            self._profile = self.lab.call(GetStation())
        return self._profile

    def update_profile(self, profile: Dict[str, Any]) -> None:
        """Hand an edited profile to the lab, which checks, saves and applies it
        (LabError when it refuses)."""
        self._profile = self.lab.call(UpdateStation(profile=profile))

    def load_profile(self, path) -> None:
        """Work with another profile; the lab refuses while measurements run."""
        self.lab.call(LoadStation(path=str(path)))

    def new_profile(self, path, title: str) -> None:
        self.lab.call(NewStation(path=str(path), title=title))

    def reload(self) -> None:
        """The profile again as its file holds it."""
        path = self.profile().path
        if path is not None:
            self.load_profile(path)

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

    def _profile_changed(self, body: StationChanged) -> None:
        self._forget_devices()
        another, self._path = body.path != self._path, body.path
        (self.station_changed if another else self.config_changed).emit()

    def _resynced(self, *_) -> None:
        """Events were lost (the daemon restarted): all is asked anew."""
        self._forget_devices()
        self._path = self.profile().path
        self.station_changed.emit()

    def running(self) -> List[RunInfo]:
        """Measurements running in the lab, whoever started them."""
        return [run for run in self.lab.call(ListRuns()) if run.status == RUNNING]

    def busy(self) -> bool:
        return any(run.running for run in self.runs)

    def title_of(self, ref: str) -> str:
        return next((d.title for d in self.devices() if d.ref == ref), ref)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop hearing the lab and calling it; the lab goes on (its daemon ends
        when it is told to or idles)."""
        self.bridge.stop()
        self.calls.stop(timeout)
