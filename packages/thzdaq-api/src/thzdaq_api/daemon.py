"""The daemon itself: what it is and holds, how it is stopped or restarted."""

from enum import Enum
from typing import Dict, Optional, Tuple

import msgspec

from thzdaq_api.measurements import RunInfo
from thzdaq_api.operation import Operation, Rights
from thzdaq_api.rights import Decision
from thzdaq_api.scripts import ScriptInfo
from thzdaq_api.station import ConnectionInfo

# Changes with the contract: a client and a daemon of other versions do not talk
API_VERSION = 1


class HostInfo(msgspec.Struct, frozen=True):
    """Where a running daemon serves, written once it does (the host file)."""

    pid: int
    port: int
    token: str  # every request carries it: only who can read the file talks
    api_version: int
    app_version: str
    executable: str  # the installation that runs it
    started: str  # wall time, ISO
    station: Optional[str]  # the profile's file
    simulate: bool


class Installation(msgspec.Struct, frozen=True):
    """The build that started last (the install file): a client from PyPI
    without the daemon package starts that build's daemon."""

    program: str  # its ThzDAQ.exe, which runs the daemon with --serve
    app_version: str


class Health(msgspec.Struct, frozen=True):
    """What /health answers: enough to know it is the daemon a client expects."""

    pid: int
    api_version: int
    app_version: str
    simulate: bool


class ProcessInfo(msgspec.Struct, frozen=True):
    pid: int
    api_version: int
    app_version: str
    executable: str  # the installation that runs it
    started: str  # wall time, ISO
    port: int
    simulate: bool


class ClientInfo(msgspec.Struct, frozen=True):
    """A client listening to the events: a GUI window, a CLI, an agent."""

    kind: str  # gui, cli, cli:answers, mcp, assistant, script
    pid: int
    origin: str
    since: str  # wall time, ISO


class LaneInfo(msgspec.Struct, frozen=True):
    """The queue of one instrument: what waits and what runs now."""

    instrument: str
    pending: int
    current: Optional[str] = None  # the device the running job talks to
    busy_for: float = 0.0  # seconds the running job has taken
    stuck: bool = False  # running for longer than a job should


class PollInfo(msgspec.Struct, frozen=True):
    ref: str
    interval: float
    subscribers: int


class DaemonStatus(msgspec.Struct, frozen=True):
    process: ProcessInfo
    station: str  # the profile's name
    path: Optional[str]  # its file
    opened: Tuple[str, ...]  # instruments open now
    clients: Tuple[ClientInfo, ...]
    runs: Tuple[RunInfo, ...]  # measurements running
    lanes: Tuple[LaneInfo, ...]
    connections: Tuple[ConnectionInfo, ...]
    polls: Tuple[PollInfo, ...]
    seq: int  # the last event
    problems: Tuple[str, ...]  # stuck lanes, broken connections
    scripts: Tuple[ScriptInfo, ...] = ()  # scripts running


class Heartbeat(msgspec.Struct, frozen=True):
    """Every couple of seconds on each event stream: the daemon is alive."""

    seq: int
    clients: int
    runs: int
    problems: Tuple[str, ...] = ()


class StopMode(str, Enum):
    GRACEFUL = "graceful"  # refused while measurements run
    CANCEL = "cancel"  # cancel them (their on_exit runs), go to the safe state
    ABORT = "abort"  # as cancel, and break reads that hang first


class GetDaemonStatus(Operation[DaemonStatus]):
    """What the daemon is and holds now: its process, the profile, clients,
    running measurements and scripts, instrument queues, connections, polls
    and problems."""


class StopDaemon(Operation[None]):
    """Stop the daemon. graceful is refused while measurements or scripts run;
    cancel ends them (their on_exit restores what they changed) and sets the
    profile's safe state; abort also breaks reads that hang. Clients lose the
    connection."""

    rights = Rights.DAEMON
    mode: StopMode = StopMode.GRACEFUL


class DaemonSettings(msgspec.Struct, frozen=True):
    """What the daemon keeps in its daemon.json."""

    idle_timeout: float  # s with no client and no measurement before it ends; 0: never
    # What agents may do by the rights a call needs (rights.AGENTS until changed)
    agents: Dict[Rights, Decision] = {}


class GetDaemonSettings(Operation[DaemonSettings]):
    """The daemon's settings: how long it waits idle before it ends, and what
    agents may do by the rights a call needs (allow, ask, deny)."""


class SetDaemonSettings(Operation[DaemonSettings]):
    """Change the daemon's settings, those given; they are kept for its next
    starts. agents changes what agents may do by rights (allow, ask, deny):
    station and answer stay deny, and only people change it."""

    rights = Rights.DAEMON
    idle_timeout: Optional[float] = None
    agents: Dict[Rights, Decision] = {}


class ReadDaemonLog(Operation[Tuple[str, ...]]):
    """The last lines of the daemon's log; none when it keeps no log file."""

    lines: int = 100


class ResetLane(Operation[bool]):
    """An instrument that does not answer holds its queue: break its commands
    and give it a new queue. Calls waiting in the old one fail at once; the one
    that hangs ends when its read is broken. Returns whether it had a queue."""

    rights = Rights.DAEMON
    instrument: str


class RestartDaemon(Operation[None]):
    """Stop the daemon as stop_daemon does and start it again with the same
    profile; clients reconnect and take a new snapshot."""

    rights = Rights.DAEMON
    mode: StopMode = StopMode.GRACEFUL
