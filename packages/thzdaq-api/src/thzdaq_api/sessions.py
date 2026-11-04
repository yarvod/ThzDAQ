"""A script's own measurement: a session the daemon keeps while a script drives
it from outside (lab.measurement, thzdaq_api.script).

A session is a measurement like any other: a number, a file, leases on its
devices, events windows draw from. The script records into it, tells its
progress and what the daemon restores when it ends, however it ends: by the
script, by a cancel (thzdaq cancel, Stop in a window), or when the script falls
silent (it died, its terminal closed), which ends it interrupted.

Calls that belong to a session carry its number (session in read_device,
set_quantity, call_action): the session's leases are their own, and what a
person allowed when it started (its devices) is not asked again, except a
dangerous step or another measurement's sweep.
"""

from typing import Any, Dict, Optional, Tuple, Union

import msgspec

from thzdaq_api.devices import QuantityValue
from thzdaq_api.measurement_file import Column
from thzdaq_api.measurements import PlotInfo, RunInfo
from thzdaq_api.operation import Operation, Rights

SILENT_S = 10.0  # a script silent this long is gone: its session is interrupted
KEEP_S = 2.0  # how long keep_session waits for a cancel before it answers


class ScriptSource(msgspec.Struct, frozen=True):
    """The script a session ran, kept with its data to measure the same again."""

    path: str
    sha256: str
    text: str


class SessionState(msgspec.Struct, frozen=True):
    """How a session stands: cancelled is a request to stop (end it cancelled)."""

    id: int
    status: str  # running, or how it ended
    cancelled: bool = False


class SweepValues(msgspec.Struct, frozen=True):
    values: Tuple[float, ...]
    unit: str  # the SI unit of the values


class StartSession(Operation[RunInfo]):
    """Start a script's own measurement (a session) named title: its file,
    number and events as any measurement has. devices it uses (shared), those
    of them it sweeps (exclusive: another's change spoils its data), and those
    it agrees to share while another measurement sweeps them (share). A device
    it uses later without naming it joins then. silent: seconds without a word
    from the script (keep_session) before the session ends interrupted and the
    daemon restores what the script asked to restore."""

    rights = Rights.RUN
    title: str
    devices: Tuple[str, ...] = ()
    exclusive: Tuple[str, ...] = ()
    share: Tuple[str, ...] = ()
    parameters: Dict[str, Any] = {}
    comment: str = ""
    workspace: Optional[str] = None
    script: Optional[ScriptSource] = None
    columns: Tuple[Column, ...] = ()  # titles and units of record keys
    total: Optional[int] = None  # steps, when known
    silent: float = SILENT_S


class KeepSession(Operation[SessionState]):
    """The script of a session is alive: the daemon keeps the session. Waits up
    to wait seconds (at most 5) for a cancel and answers at once when one comes."""

    id: int
    wait: float = 0.0


class RecordSession(Operation[SessionState]):
    """Records of a session's table, values encoded as in measurement files
    (thzdaq_api.data); columns describe keys (title, unit, source) the session
    does not know yet or describes anew."""

    rights = Rights.RUN
    id: int
    table: str
    rows: Tuple[Dict[str, Any], ...]
    columns: Tuple[Column, ...] = ()


class AdvanceSession(Operation[SessionState]):
    """Progress of a session: done steps (one more when not given) of total."""

    rights = Rights.RUN
    id: int
    done: Optional[int] = None
    total: Optional[int] = None


class LogSession(Operation[None]):
    """A line of a session's log, shown where the measurement is followed."""

    rights = Rights.RUN
    id: int
    message: str


class PlotSession(Operation[PlotInfo]):
    """A plot of a session's records, drawn from now on and kept in its file;
    labels left empty take the columns' titles and units. Returns it as drawn."""

    rights = Rights.RUN
    id: int
    plot: PlotInfo


class RestoreOnExit(Operation[QuantityValue]):
    """When the session ends, however it ends, the daemon sets this quantity of
    a device back to the value it has now (returned), in steps where the bench
    limits ask for them."""

    rights = Rights.SET
    id: int
    ref: str
    key: str


class CallOnExit(Operation[None]):
    """When the session ends, however it ends, the daemon makes a device do an
    action (to_cold); arguments as call_action takes them."""

    rights = Rights.SET
    id: int
    ref: str
    action: str
    arguments: Dict[str, Union[bool, int, float, str]] = msgspec.field(
        default_factory=dict
    )


class EndSession(Operation[RunInfo]):
    """End a session as the script ended: completed, cancelled (it was asked
    to), failed (error and traceback say why) or interrupted (stopped by hand).
    The daemon restores what it was asked to, then the measurement ends."""

    rights = Rights.STOP
    id: int
    status: str = "completed"
    error: Optional[str] = None
    traceback: str = ""


class ParseSweep(Operation[SweepValues]):
    """The values of a sweep typed as people type it, start:stop:points in a
    unit ("2:3:51" in mV), as SI values with their SI unit."""

    text: str
    unit: str = ""
