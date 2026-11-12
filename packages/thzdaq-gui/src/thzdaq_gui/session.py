import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, TypeVar

from PySide6.QtCore import QObject, Signal
from thzdaq_api.custom import (
    SUFFIX,
    CustomInfo,
    CustomLibrary,
    ListCustom,
    procedure_name,
)
from thzdaq_api.devices import (
    DescribeDevice,
    DeviceDescription,
    DeviceInfo,
    ListDevices,
)
from thzdaq_api.events import GetSnapshot, StationChanged
from thzdaq_api.lab import Lab
from thzdaq_api.leases import LeaseInfo, ListLeases
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.measurements import (
    ListProcedures,
    ListRuns,
    ProcedureSummary,
    RunInfo,
)
from thzdaq_api.operation import Operation
from thzdaq_api.origins import ASSISTANT, ASSISTANT_CLIENT, GUI
from thzdaq_api.procedures import current_name
from thzdaq_api.ui import window_id
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
from thzdaq_gui.folders import MEASUREMENTS, PROFILES, SCRIPTS, Folders
from thzdaq_gui.measurements import MeasurementsModel
from thzdaq_gui.processes import Processes
from thzdaq_gui.settings import stations_dir
from thzdaq_gui.models.run import RunModel
from thzdaq_gui.models.runs import RunEvents
from thzdaq_gui.models.scripts import ScriptsModel
from thzdaq_gui.workers import DeviceWorker
from thzdaq_gui.workspace import Workspace

logger = logging.getLogger(__name__)
R = TypeVar("R")


class Connect(Protocol):
    def __call__(self, simulate: bool, origin: str = GUI, kind: str = GUI) -> Lab:
        """The lab of the bench, or of its simulator (simulate): a daemon to
        call as origin, listened to as a client of kind."""


class Session(QObject):
    """What the window works with: the lab, the profile it works with, its
    workspace (whose data/ gets its measurements), the measurements it shows
    and the calls in the background.

    lab is the bench as the daemon's clients call it, the daemon of the
    instruments or of their simulator; bridge brings its events to the GUI
    thread, calls runs its operations in the background, a queue per
    instrument. The profile belongs to the lab: Setup edits it (update_profile),
    the File menu loads another one, and the session follows what the lab
    tells: station_changed for another profile or another lab,
    config_changed for an edited one. window is the id the window listens
    as: agents ask it by that id (thzdaq_api.ui).
    """

    station_changed = Signal()  # another profile, or another lab: build anew
    procedures_changed = Signal()  # the bench's own measurements changed
    config_changed = Signal()  # the profile was edited: devices may differ
    leases_changed = Signal()  # measurements took or gave back devices

    def __init__(self, lab_of: Connect, workspace, parent=None):
        super().__init__(parent)
        # Not "connect": that name of a QObject connects its signals
        self.lab_of = lab_of
        self.window = window_id()
        # Its data/ gets the measurements this window starts
        self.workspace = Workspace(workspace, self)
        self.calls = DeviceWorker(self)
        self.measurements = MeasurementsModel(self, self)
        # Where file dialogs start until the user picks a folder of a kind
        self.folders = Folders(
            {
                MEASUREMENTS: lambda: self.data_root,
                PROFILES: stations_dir,
                SCRIPTS: lambda: self.workspace.scripts,
            }
        )
        self.runs: List[RunModel] = []
        self.processes = Processes(self)  # what runs now, for the Processes dock
        self.lab: Optional[Lab] = None
        self.simulate = False
        # The other daemon (instruments or simulator) after a switch: it goes on
        self.left: Optional[Lab] = None
        self.bridge = Bridge(self)
        self.run_events = RunEvents(self)
        self.run_events.remembered.connect(self.measurements.remember)
        # Scripts of the workspace, and those the daemon runs
        self.scripts = ScriptsModel(self, self)
        self.values = {}
        self.bridge.values.connect(self._values_heard)
        self.bridge.quantity_set.connect(self._quantity_heard)
        self.bridge.raw_sent.connect(self._raw_heard)
        self.bridge.station_changed.connect(self._profile_changed)
        self.bridge.procedures_changed.connect(self._procedures_heard)
        self.bridge.resync.connect(self._resynced)
        self.bridge.leases_changed.connect(self._leases_heard)
        self._procedures: Optional[Tuple[ProcedureSummary, ...]] = None
        self._library: Optional[CustomLibrary] = None
        self._drivers: Optional[Dict[str, DriverInfo]] = None
        self._connection_kinds: Optional[Tuple[ConnectionKindInfo, ...]] = None
        self._path: Optional[str] = None  # of the profile heard last
        self._leases: Optional[Tuple[LeaseInfo, ...]] = None
        self._forget_devices()

    def open(self, simulate: bool) -> None:
        """Work with the lab of the instruments, or of their simulator;
        LabError when it cannot be reached."""
        lab = self.lab_of(simulate, GUI, GUI, self.window)
        self.bridge.stop()
        if self.lab is not None and simulate != self.simulate:
            self.run_events.detach()
            self.left = self.lab
        self.lab, self.simulate = lab, simulate
        # Events from the snapshot on: nothing between them is missed
        snapshot = lab.call(GetSnapshot())
        self.values = snapshot.values
        self._forget_devices()
        self._leases = None
        self._path = self.profile().path
        logger.info(f"Working with {self._path} (simulate={simulate})")
        self.station_changed.emit()
        self.run_events.refresh()
        self.bridge.listen(lab, snapshot.seq)

    @property
    def data_root(self) -> Path:
        return self.workspace.data

    def assistant_lab(self) -> Lab:
        """The lab this window works with, called as its assistant: an agent
        whose changes wait for the person; LabError when it cannot be reached."""
        return self.lab_of(self.simulate, ASSISTANT, ASSISTANT_CLIENT)

    def run_model(self) -> RunModel:
        """The runs of one procedure box; Data lists what they measure, with
        the workspace each was made in."""
        run = RunModel(self, self.title_of, self)
        run.started.connect(
            lambda measurement: self.measurements.add(measurement, run.run.workspace)
        )
        run.finished.connect(self.measurements.refresh_item)
        self.runs.append(run)
        return run

    def call(self, operation: Operation[R]) -> R:
        """An operation of the lab now."""
        return self.lab.call(operation)

    def procedures(self) -> Tuple[ProcedureSummary, ...]:
        """The procedures the bench runs, with their plots: asked once, then
        as the daemon tells them changed (its own measurements)."""
        if self._procedures is None:
            self._procedures = self.lab.call(ListProcedures())
        return self._procedures

    def procedure(self, name: str) -> Optional[ProcedureSummary]:
        """By its name now or one it had before (RENAMED); None for one the
        bench runs no more (a script taken away)."""
        name = current_name(name)
        return next((p for p in self.procedures() if p.name == name), None)

    def _procedures_heard(self, body) -> None:
        self._procedures = body.procedures
        self._library = None
        self.procedures_changed.emit()

    def library(self) -> CustomLibrary:
        """The bench's own measurements: their scripts, where they are."""
        if self._library is None:
            self._library = self.lab.call(ListCustom())
        return self._library

    def custom(self, procedure: str) -> Optional[CustomInfo]:
        """The script of one of the bench's own measurements."""
        return next(
            (m for m in self.library().measurements if m.procedure == procedure), None
        )

    def custom_of(self, path: Path) -> Optional[str]:
        """The bench's own measurement a file is the script of: custom.<name>
        for a file of the library, described yet or not; None for another."""
        file = Path(path).resolve()
        if file.suffix != SUFFIX:
            return None
        if file.parent != Path(self.library().folder).resolve():
            return None
        return procedure_name(file.stem)

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

    def leases(self) -> Tuple[LeaseInfo, ...]:
        """Who uses which device now: read, set or swept by a measurement."""
        if self._leases is None:
            self._leases = self.lab.call(ListLeases())
        return self._leases

    def _leases_heard(self, body) -> None:
        self._leases = body.leases
        self.leases_changed.emit()

    def _resynced(self, *_) -> None:
        """Events were lost (the daemon restarted): all is asked anew."""
        self._forget_devices()
        self._leases = None
        self._path = self.profile().path
        snapshot = self.call(GetSnapshot())
        self.values = snapshot.values
        self.station_changed.emit()
        self.run_events.refresh()
        self.bridge.listen(self.lab, snapshot.seq)

    def _values_heard(self, body) -> None:
        self.values.setdefault(body.ref, {}).update(body.values)

    def _quantity_heard(self, body) -> None:
        self.values.setdefault(body.ref, {})[body.key] = body.value

    def _raw_heard(self, body) -> None:
        """A raw command: in the log; after a write nothing is known of the
        devices on the instrument until they are read again."""
        answer = "" if body.answer is None else f": {body.answer}"
        logger.info(f"{body.origin} → {body.instrument} {body.command}{answer}")
        for ref in body.unknown:
            self.values.pop(ref, None)

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
        self.scripts.close(timeout)
