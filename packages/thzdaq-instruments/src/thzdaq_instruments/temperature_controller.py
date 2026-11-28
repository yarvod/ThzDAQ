"""What a temperature controller (LakeShore 336) is, for its driver and its
simulator: inputs A-D, and heater outputs 1 and 2 as channels heater1 and
heater2, each with its range, how it is driven (a PID loop on an input, a
zone table, or open loop at a manual output) and its loop.

A heater's settings are names (its range "low", its mode "open loop"): the
driver turns them into the numbers of the commands.
"""

from dataclasses import dataclass, replace
from typing import Dict, Mapping, Sequence

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import Quantity

INPUTS = ("A", "B", "C", "D")
# Channel keys of the heater outputs, by output number
HEATERS: Dict[str, int] = {"heater1": 1, "heater2": 2}

# By their numbers in the commands (RANGE, OUTMODE, HTRST?)
HEATER_RANGES = ("off", "low", "medium", "high")
CONTROL_MODES = ("off", "closed loop PID", "zone", "open loop")
CONTROL_INPUTS = ("none", *INPUTS)
HEATER_STATES = ("ok", "open load", "short")


def number_of(names: Sequence[str], name: str) -> int:
    """The number a command takes for a setting named (one of names)."""
    if name not in names:
        raise ConfigurationError(f"{name!r} is not one of {list(names)}")
    return names.index(name)


@dataclass(frozen=True)
class OutputMode:
    """How a heater output is driven (OUTMODE)."""

    mode: str  # one of CONTROL_MODES
    input: str  # the input its loop follows, one of CONTROL_INPUTS
    powerup_enable: bool = False  # driven again after a power cycle


@dataclass(frozen=True)
class Pid:
    """The loop of a heater output in closed loop (PID)."""

    p: float  # gain
    i: float  # reset
    d: float  # rate, %


def _mode(target) -> OutputMode:
    return target.get_mode()


def _pid(target) -> Pid:
    return target.get_pid()


# Setpoints the guard checks against the passport (HEATER_LIMITS) and the bench
SETPOINT = Quantity(
    "setpoint", "Setpoint", "K",
    get=lambda t: t.get_setpoint(), setters=("set_setpoint",),
)  # fmt: skip
MANUAL_OUTPUT = Quantity(
    "manual_output", "Manual output", "%",
    get=lambda t: t.get_manual_output(), setters=("set_manual_output",),
)  # fmt: skip

# A heater output, in the order its dock shows it: what is set, then what it does
HEATER_QUANTITIES = (
    Quantity(
        "heater_range", "Heater range", kind="text", choices=HEATER_RANGES,
        get=lambda t: t.get_range(), set=lambda t, v: t.set_range(str(v)),
    ),
    Quantity(
        "control_mode", "Control mode", kind="text", choices=CONTROL_MODES,
        source=_mode, field="mode",
        set=lambda t, v: t.set_mode(replace(t.get_mode(), mode=str(v))),
    ),
    Quantity(
        "control_input", "Control input", kind="text", choices=CONTROL_INPUTS,
        source=_mode, field="input",
        set=lambda t, v: t.set_mode(replace(t.get_mode(), input=str(v))),
    ),
    SETPOINT,
    MANUAL_OUTPUT,
    Quantity(
        "pid_p", "PID P", source=_pid, field="p",
        set=lambda t, v: t.set_pid(replace(t.get_pid(), p=float(v))),
        minimum=0.1, maximum=1000,
    ),
    Quantity(
        "pid_i", "PID I", source=_pid, field="i",
        set=lambda t, v: t.set_pid(replace(t.get_pid(), i=float(v))),
        minimum=0.1, maximum=1000,
    ),
    Quantity(
        "pid_d", "PID D", "%", source=_pid, field="d",
        set=lambda t, v: t.set_pid(replace(t.get_pid(), d=float(v))),
        minimum=0, maximum=200,
    ),
    Quantity("heater_output", "Heater output", "%", get=lambda t: t.get_output()),
    Quantity(
        "heater_status", "Heater status", kind="text", choices=HEATER_STATES,
        get=lambda t: t.get_status(),
    ),
)  # fmt: skip

# The passport of a heater output: what the controller accepts at all
HEATER_LIMITS: Mapping[str, Limit] = {
    SETPOINT.key: Limit(minimum=0.0),
    MANUAL_OUTPUT.key: Limit(0.0, 100.0),
}
