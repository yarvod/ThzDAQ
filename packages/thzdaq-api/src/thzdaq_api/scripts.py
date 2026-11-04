"""Scripts the daemon runs (thzdaq script start): a file run by an interpreter
apart from any terminal, so it outlives the one it was started from. Its
output goes to <workspace>/data/scripts/<id>.log; it finds the daemon that
started it by THZDAQ_SCRIPT_ID and THZDAQ_SIMULATE, works in its workspace
(THZDAQ_WORKSPACE) and calls the daemon as script:<name>@<id>.

A script started without a person nearby may be allowed in advance what it
would otherwise ask for (allow): set:<ref> its quantities, call:<ref> its
actions, run:<procedure> a built-in procedure; a session (lab.measurement)
starts without asking when every device it names is allowed. A dangerous step
is never allowed in advance. share names devices its measurements share while
another one sweeps them. Who starts the script allows these: a person by
typing them, an agent's start is asked of a person with them shown.
"""

from typing import Optional, Tuple

import msgspec

from thzdaq_api.operation import Operation, Rights

SCRIPTS = "scripts"  # the folder of a workspace's data/ that holds their logs
SCRIPT_ID_ENV = "THZDAQ_SCRIPT_ID"  # a script the daemon started: its number
SIMULATE_ENV = "THZDAQ_SIMULATE"  # "1": the daemon that started it simulates
STOP_S = 5.0  # a stopped script has this long to end after its cancel

# Statuses of a script
RUNNING = "running"
EXITED = "exited"  # ended by itself (exit_code says how)
STOPPED = "stopped"  # ended by stop_script

# What may be allowed in advance: <kind>:<target>
SET, CALL, RUN = "set", "call", "run"
KINDS = (SET, CALL, RUN)
SEPARATOR = ":"


class Grant(msgspec.Struct, frozen=True):
    """Allowed in advance: set (quantities) or call (actions) of a device by
    its ref, or run a built-in procedure by its name."""

    kind: str
    target: str

    def __str__(self) -> str:
        return f"{self.kind}{SEPARATOR}{self.target}"

    @classmethod
    def parse(cls, text: str) -> "Grant":
        """ "set:sis_bias_1" -> Grant("set", "sis_bias_1"); ValueError otherwise."""
        kind, separator, target = text.strip().partition(SEPARATOR)
        if not separator or kind not in KINDS or not target:
            raise ValueError(
                f"{text!r}: allow {', '.join(f'{k}:…' for k in KINDS)}"
                " (set:sis_bias_1, call:chopper_1, run:sis.iv_curve)"
            )
        return cls(kind, target)


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


class ScriptLog(msgspec.Struct, frozen=True):
    """Output of a script from an offset: more follows from next while it runs."""

    text: str
    next: int
    running: bool


class StartScript(Operation[ScriptInfo]):
    """Run a Python script apart from any terminal: python is how a file is run
    ([python], or a build's [thzdaq-cli.exe, run-script]), arguments go after
    the file, workspace is its working folder (its log under data/scripts).
    allow: what it may do without asking (set:<ref>, call:<ref>,
    run:<procedure>; never a dangerous step); share: devices it shares while
    another measurement sweeps them."""

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
