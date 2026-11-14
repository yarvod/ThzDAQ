"""Scripts the daemon runs (thzdaq script start): a file run by an interpreter
apart from any terminal, so it outlives the one it was started from. Its
output goes to <workspace>/data/scripts/<id>.log; it finds the daemon that
started it by THZDAQ_SCRIPT_ID and THZDAQ_SIMULATE, works in its workspace
(THZDAQ_WORKSPACE) and calls the daemon as script:<name>@<id>.

A script has the rights of whoever started it (thzdaq_api.rights): a
person's changes the bench as the person would in a dock, an agent's asks as
the agent does. A person may allow their script in advance what it would
otherwise ask for (allow): set:<ref> its quantities, call:<ref> its actions
(a jump or a value beyond the warn range), run:<procedure> a procedure,
raw:<instrument> raw writes to an instrument (lab.raw), which no limit checks;
a session (lab.measurement) starts without asking when every device it names
is allowed. A dangerous step is never allowed in advance. share names devices
its measurements share while another one sweeps them. An agent's allow and
share allow nothing.
"""

from typing import Optional, Tuple

import msgspec

from thzdaq_api.operation import Operation, Rights
from thzdaq_api.procedures import current_name

SCRIPTS = "scripts"  # the folder of a workspace's data/ that holds their logs
SCRIPT_ID_ENV = "THZDAQ_SCRIPT_ID"  # a script the daemon started: its number
SIMULATE_ENV = "THZDAQ_SIMULATE"  # "1": the daemon that started it simulates
STOP_S = 5.0  # a stopped script has this long to end after its cancel
OUTPUT_ENV = {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

# Statuses of a script
RUNNING = "running"
EXITED = "exited"  # ended by itself (exit_code says how)
STOPPED = "stopped"  # ended by stop_script

# What may be allowed in advance: <kind>:<target>
SET, CALL, RUN, RAW = "set", "call", "run", "raw"
KINDS = (SET, CALL, RUN, RAW)
SEPARATOR = ":"


class Grant(msgspec.Struct, frozen=True):
    """Allowed in advance: set (quantities) or call (actions) of a device by
    its ref, run a built-in procedure by its name, or raw writes to an
    instrument by its id."""

    kind: str
    target: str

    def __str__(self) -> str:
        return f"{self.kind}{SEPARATOR}{self.target}"

    @classmethod
    def parse(cls, text: str) -> "Grant":
        """ "set:sis_bias_1" -> Grant("set", "sis_bias_1"); a procedure by
        the name it has now; ValueError otherwise."""
        kind, separator, target = text.strip().partition(SEPARATOR)
        if not separator or kind not in KINDS or not target:
            raise ValueError(
                f"{text!r}: allow {', '.join(f'{k}:…' for k in KINDS)}"
                " (set:sis_bias_1, call:chopper_1, run:sis.current_vs_voltage,"
                " raw:signal_generator_1)"
            )
        return cls(kind, current_name(target) if kind == RUN else target)


class ScriptInfo(msgspec.Struct, frozen=True):
    """A script the daemon runs or ran."""

    id: int
    name: str  # its file's name without the suffix
    path: str
    command: Tuple[str, ...]  # what was started
    workspace: str  # its working folder; its log is under data/scripts
    log: str
    origin: str  # what it calls the daemon as: script:<name>@<id>
    by: str  # who started it
    pid: Optional[int]
    status: str  # running, exited, stopped
    started: str
    ended: Optional[str] = None
    exit_code: Optional[int] = None
    allow: Tuple[Grant, ...] = ()
    share: Tuple[str, ...] = ()
    # The measurement it was started for: a run of the bench's own (custom.*)
    measurement: Optional[int] = None


class ScriptLog(msgspec.Struct, frozen=True):
    """UTF-8 output with CRLF as LF; next is a byte offset in the original log,
    not the encoded length of text. More follows while the script runs."""

    text: str
    next: int
    running: bool


class StartScript(Operation[ScriptInfo]):
    """Run a Python script apart from any terminal: python is how a file is run
    ([python], or a build's [thzdaq-cli.exe, run-script]), arguments go after
    the file, workspace is its working folder (its log under data/scripts).
    allow: what it may do without asking (set:<ref>, call:<ref>,
    run:<procedure>, raw:<instrument> raw writes; never a dangerous step);
    share: devices it shares while another measurement sweeps them."""

    rights = Rights.RUN
    path: str
    python: Tuple[str, ...]
    arguments: Tuple[str, ...] = ()
    workspace: Optional[str] = None
    allow: Tuple[Grant, ...] = ()
    share: Tuple[str, ...] = ()


class ListScripts(Operation[Tuple[ScriptInfo, ...]]):
    """Scripts the daemon runs, and those that ended lately."""


class ReadScriptLog(Operation[ScriptLog]):
    """A script's output from byte since (0: from its start), up to a part at a
    time; call again from next while it runs."""

    id: int
    since: int = 0


class StopScript(Operation[ScriptInfo]):
    """Stop a script: its measurements are cancelled (they restore what they
    changed), and a script that has not ended a few seconds later is ended."""

    rights = Rights.STOP
    id: int
