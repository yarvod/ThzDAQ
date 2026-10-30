"""Procedures and the measurements running in the daemon."""

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import msgspec

from thzdaq_api.devices import DeviceInfo
from thzdaq_api.operation import Operation, Rights

DATA = "data"  # the folder of a workspace that holds its measurements
PLANNED = "planned"  # a run as a dry run of start_measurement says it would go

# Items of a list parameter typed as text: "4, 6; 8"
LIST_SEPARATORS = re.compile(r"[,;\s]+")


def split_list(text: str) -> List[str]:
    """ "4, 6; 8" -> ["4", "6", "8"]"""
    return [item for item in LIST_SEPARATORS.split(str(text).strip()) if item]


class ParameterInfo(msgspec.Struct, frozen=True):
    """A parameter of a procedure; values in SI units, shown in display units
    (value / display_scale)."""

    name: str
    label: str
    kind: str  # float, int, bool, choice, sweep, float_list, string_list, ...
    unit: str = ""
    display_unit: str = ""
    display_scale: float = 1.0
    default: Any = None  # as JSON: a sweep is {start, stop, points}
    required: bool = False
    help: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()
    max_points: Optional[int] = None  # of a sweep


class SlotInfo(msgspec.Struct, frozen=True):
    """A device a procedure needs, by the capabilities it must have (none: any
    device)."""

    name: str
    title: str
    capabilities: Tuple[str, ...]
    kind: Optional[str] = None  # the device kind preferred: sis_bias

    def suits(self, device: DeviceInfo) -> bool:
        return set(self.capabilities) <= set(device.capabilities)

    def candidates(self, devices: Iterable[DeviceInfo]) -> List[DeviceInfo]:
        """Devices that suit it; only those of the preferred kind when there
        are any (a SIS bias slot lists SIS biases, not every supply channel)."""
        suitable = [device for device in devices if self.suits(device)]
        preferred = [device for device in suitable if device.kind == self.kind]
        return preferred or suitable


GroupKey = Tuple[Any, ...]


class PlotInfo(msgspec.Struct, frozen=True):
    """A plot of the records of one table, independent of any plotting library.

    Values in records are SI; x_scale / y_scale convert them for display
    (value / scale), e.g. x_scale=1e9 shows Hz as GHz. Records with different
    values of the group_by keys form separate curves; kind="map" draws z over
    x and y. A procedure declares its plots so; a viewer draws them so.
    """

    key: str
    title: str
    table: str
    x: str
    y: str
    x_label: str = ""
    y_label: str = ""
    x_scale: float = 1.0
    y_scale: float = 1.0
    group_by: Tuple[str, ...] = ()
    kind: str = "line"  # line, scatter or map (z over x and y)
    z: Optional[str] = None
    z_label: str = ""
    z_scale: float = 1.0
    analysis: Optional[str] = None  # an analysis a viewer may offer: iv
    # Only records with these values: (("plot", "P-t"),) in a monitor table
    where: Tuple[Tuple[str, Any], ...] = ()

    def accepts(self, record: Mapping[str, Any]) -> bool:
        return all(record.get(key) == value for key, value in self.where)

    def group_key(self, record: Mapping[str, Any]) -> GroupKey:
        return tuple(record.get(key) for key in self.group_by)

    def label(self, group: GroupKey) -> str:
        return " ".join(f"{value}" for value in group if value is not None)

    def point(self, record: Mapping[str, Any]) -> Optional[Tuple[float, ...]]:
        """Display coordinates of a record, None when a value is missing."""
        if not self.accepts(record):
            return None
        keys = (self.x, self.y) + ((self.z,) if self.kind == "map" else ())
        scales = (self.x_scale, self.y_scale) + (
            (self.z_scale,) if self.kind == "map" else ()
        )
        values = []
        for key, scale in zip(keys, scales):
            value = record.get(key)
            if value is None:
                return None
            values.append(value / scale)
        return tuple(values)

    def curves(
        self, records: Iterable[Mapping[str, Any]]
    ) -> Dict[GroupKey, List[Tuple[float, ...]]]:
        """Points per group in record order."""
        result: Dict[GroupKey, List[Tuple[float, ...]]] = {}
        for record in records:
            point = self.point(record)
            if point is not None:
                result.setdefault(self.group_key(record), []).append(point)
        return result


class ProcedureSummary(msgspec.Struct, frozen=True):
    name: str
    title: str
    description: str
    plots: Tuple[PlotInfo, ...] = ()  # every plot it may fill


class ProcedureInfo(msgspec.Struct, frozen=True):
    """A procedure as a run with the parameters (and devices) described goes:
    the slots it needs, the plots it fills, its steps (None: no end known) and
    the seconds of x its live plots keep (None: all of it)."""

    name: str
    title: str
    description: str
    parameters: Tuple[ParameterInfo, ...]
    slots: Tuple[SlotInfo, ...]
    plots: Tuple[PlotInfo, ...]
    steps: Optional[int] = None
    plot_window: Optional[float] = None


class RunInfo(msgspec.Struct, frozen=True):
    """A measurement started in the daemon: running or how it ended."""

    id: int
    procedure: str
    title: str
    status: str  # running, completed, cancelled, failed; planned for a dry run
    devices: Dict[str, str]  # slot -> device
    origin: str  # who started it
    comment: str = ""
    done: int = 0
    total: Optional[int] = None  # steps; None: no end known
    started: str = ""
    finished: Optional[str] = None
    error: Optional[str] = None
    path: Optional[str] = None  # the file it is saved in
    workspace: Optional[str] = None  # the folder whose data/ holds it
    # Conflicts accepted with share, as the measurement notes them
    conflicts: Tuple[Dict[str, Any], ...] = ()


class ListProcedures(Operation[Tuple[ProcedureSummary, ...]]):
    """Every procedure the bench can run, with what it measures."""


class DescribeProcedure(Operation[ProcedureInfo]):
    """A procedure's parameters (units, defaults, limits), the devices it needs,
    its plots and steps. Slots, plots and steps depend on the parameters, a
    monitor's plots on its devices (the units they read): pass them to see
    those of a run. Invalid parameters are refused, each one named."""

    procedure: str
    parameters: Dict[str, Any] = {}
    devices: Dict[str, str] = {}  # slot -> device
    typed: Dict[str, str] = {}  # parameters as people type them, as in start


class StartMeasurement(Operation[RunInfo]):
    """Start a procedure. parameters in SI units as describe_procedure lists
    them (a sweep: {"start", "stop", "points"}); devices maps slots to device
    refs. Returns at once; wait_measurement follows it. A device another
    measurement sweeps (or one this one sweeps that another uses) is a
    conflict unless share is true; both measurements record it. workspace is
    the folder of the experiment: the file goes to its data/ (the daemon's own
    folder when not given). dry_run checks all a start checks (parameters,
    devices, the limits of what it sets, conflicts) without opening an
    instrument or writing a file, and returns the run it would be, planned,
    with number 0. typed gives parameters as people type them, in the units
    they are shown in: a sweep as start:stop:points ("0:7:351" for mV), a list
    comma separated; the daemon parses them."""

    rights = Rights.RUN
    procedure: str
    parameters: Dict[str, Any] = {}
    devices: Dict[str, str] = {}
    comment: str = ""
    share: bool = False
    workspace: Optional[str] = None
    dry_run: bool = False
    typed: Dict[str, str] = {}


class ListRuns(Operation[Tuple[RunInfo, ...]]):
    """Measurements started in the daemon: those running and those that ended
    lately."""


class RunSnapshot(msgspec.Struct, frozen=True):
    """The published state of a run; follow events after seq to continue it.

    Rows use the same value encoding as MeasurementRecords. Pending batches
    are excluded: they will arrive in events after this snapshot.
    """

    run: RunInfo
    plots: Tuple[PlotInfo, ...]
    rows: Dict[str, Tuple[Dict[str, Any], ...]]
    seq: int


class GetRunSnapshot(Operation[RunSnapshot]):
    """Catch up with a running or recently finished measurement, including
    its published records and the plots of this particular run."""

    id: int


class WaitMeasurement(Operation[RunInfo]):
    """Wait until a measurement ends, at most `timeout` seconds (up to 60);
    returns how it stands. Call again while it runs."""

    long = True
    id: int
    timeout: float = 30.0


class CancelMeasurement(Operation[RunInfo]):
    """Stop a measurement: it ends after the step it is in and restores what
    it changed."""

    rights = Rights.STOP
    id: int


class SetComment(Operation[None]):
    """The comment of a measurement, by its file: a running one keeps it and
    saves it with its data; a file that ended is written with it."""

    rights = Rights.RUN
    path: str
    comment: str


class AbortMeasurement(Operation[RunInfo]):
    """Stop a measurement that waits for a device that does not answer: breaks
    the connections of its devices (they reconnect on the next command)."""

    rights = Rights.STOP
    id: int
