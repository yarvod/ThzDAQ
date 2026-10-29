"""Procedures and the measurements running in the daemon."""

from typing import Any, Dict, Optional, Tuple

import msgspec

from thzdaq_api.operation import Operation, Rights


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


class SlotInfo(msgspec.Struct, frozen=True):
    """A device a procedure needs, by the capabilities it must have."""

    name: str
    title: str
    capabilities: Tuple[str, ...]
    kind: Optional[str] = None  # the device kind preferred: sis_bias


class PlotInfo(msgspec.Struct, frozen=True):
    """A plot of the records of one table; values / scale give display units."""

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
    where: Tuple[Tuple[str, Any], ...] = ()  # only records with these values


class ProcedureSummary(msgspec.Struct, frozen=True):
    name: str
    title: str
    description: str


class ProcedureInfo(msgspec.Struct, frozen=True):
    name: str
    title: str
    description: str
    parameters: Tuple[ParameterInfo, ...]
    slots: Tuple[SlotInfo, ...]
    plots: Tuple[PlotInfo, ...]


class RunInfo(msgspec.Struct, frozen=True):
    """A measurement started in the daemon: running or how it ended."""

    id: int
    procedure: str
    title: str
    status: str  # running, completed, cancelled, failed
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


class ListProcedures(Operation[Tuple[ProcedureSummary, ...]]):
    """Every procedure the bench can run, with what it measures."""


class DescribeProcedure(Operation[ProcedureInfo]):
    """A procedure's parameters (units, defaults, limits), the devices it needs
    and its plots. Slots and plots may depend on parameters: pass them to see
    those of a run."""

    procedure: str
    parameters: Dict[str, Any] = {}


class StartMeasurement(Operation[RunInfo]):
    """Start a procedure. parameters in SI units as describe_procedure lists
    them (a sweep: {"start", "stop", "points"}); devices maps slots to device
    refs. Returns at once; wait_measurement follows it. A device another
    measurement sweeps (or one this one sweeps that another uses) is a
    conflict unless share is true; both measurements record it. workspace is
    the folder of the experiment: the file goes to its data/ (the daemon's own
    folder when not given)."""

    rights = Rights.RUN
    procedure: str
    parameters: Dict[str, Any] = {}
    devices: Dict[str, str] = {}
    comment: str = ""
    share: bool = False
    workspace: Optional[str] = None


class ListRuns(Operation[Tuple[RunInfo, ...]]):
    """Measurements started in the daemon: those running and those that ended
    lately."""


class WaitMeasurement(Operation[RunInfo]):
    """Wait until a measurement ends, at most `timeout` seconds (up to 60);
    returns how it stands. Call again while it runs."""

    long = True
    id: int
    timeout: float = 30.0


class CancelMeasurement(Operation[RunInfo]):
    """Stop a measurement: it ends after the step it is in and restores what
    it changed."""

    rights = Rights.RUN
    id: int


class AbortMeasurement(Operation[RunInfo]):
    """Stop a measurement that waits for a device that does not answer: breaks
    the connections of its devices (they reconnect on the next command)."""

    rights = Rights.RUN
    id: int
