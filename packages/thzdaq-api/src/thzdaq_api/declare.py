"""Declarations at the top of a script, which make it a measurement of its own
with a form (thzdaq_api.custom): device(...) a slot, value(...) a parameter,
plot(...) a plot it fills, instrument(...) an instrument it brings into the
profile (thzdaq_api.raw: its raw commands named by reading and setting).

    bias = device("SIS bias", kind="sis_bias")
    voltage = value("Bias voltage", "0:7:351", unit="mV")
    pv = plot("P-V", table="pv", x="voltage", y="power", group_by="load")
    gauge = instrument("gauge_1", driver="generic.scpi",
                       connection="tcp://169.254.0.50:5025",
                       pressure=reading("PR1?", unit="Pa", scale=100))

Run by the daemon (Start in a window, thzdaq run custom.x), device() is the
device chosen for the slot and value() the value given, in SI. Run as it is
(python x.py), device() is the first device that suits the slot (as a form
offers it) and value() the default, which the daemon parses: the first
declaration connects to it, and connect() returns that bench. Described, they
are only noted, and the script ends with the last one.
"""

import sys
from typing import Any, Iterable, Mapping, Optional, Union

from thzdaq_api.custom import (
    BOOL,
    DEVICE,
    FLOAT,
    FLOAT_LIST,
    INSTRUMENT,
    INT,
    PLOT,
    SWEEP,
    VALUE,
    Given,
    InstrumentDeclared,
    ParseValue,
    SlotDeclared,
    ValueDeclared,
)
from thzdaq_api.data import Measured
from thzdaq_api.declaring import STATE
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Bench, Device, connect
from thzdaq_api.measurements import PlotInfo, SlotInfo
from thzdaq_api.origins import agent
from thzdaq_api.raw import RawInstrument, Reading, named_values
from thzdaq_api.sessions import Swept
from thzdaq_api.station import DeclareInstrument


def _bench() -> Bench:
    """The bench the declarations use: connected at the first that needs it."""
    if STATE.bench is None:
        STATE.bench = connect()
    return STATE.bench


def _chosen(slot: SlotDeclared) -> str:
    """The device of a slot run as it is: the first that suits it."""
    info = SlotInfo(slot.name, slot.title, slot.capabilities, slot.kind)
    suitable = [found.ref for found in info.candidates(_bench().devices())]
    if not suitable:
        raise LabError(
            ErrorCode.NOT_FOUND,
            f"No device suits {slot.name} ({slot.title})",
            "add one in Setup, or name another kind in device(...)",
        )
    if len(suitable) > 1:
        others = ", ".join(suitable[1:])
        print(f"{slot.name}: {suitable[0]} (also {others})", file=sys.stderr)
    return suitable[0]


def device(title: str, *capabilities: str, kind: Optional[str] = None) -> Device:
    """A device the form chooses: one with the capabilities named
    ("PowerDetector"), those of the kind (sis_bias) first."""
    name = STATE.name(DEVICE, title, len(STATE.slots))
    slot = SlotDeclared(name, title, tuple(capabilities), kind)
    STATE.slots.append(slot)
    STATE.declared()
    if STATE.describing:
        return None
    given = STATE.inputs.devices.get(name) if STATE.inputs else None
    return _bench()[given or _chosen(slot)]


def python_value(given: Given, title: str) -> Any:
    """A value as the script uses it: a number with its unit (Measured), a
    sweep for m.sweep (Swept), the rest as it is."""
    if given.kind == FLOAT:
        return Measured(given.value, given.unit, title)
    if given.kind == INT:
        return int(given.value)
    if given.kind == BOOL:
        return bool(given.value)
    if given.kind == SWEEP:
        return Swept(
            given.value["start"], given.value["stop"], given.value["points"],
            given.unit,
        )  # fmt: skip
    if given.kind == FLOAT_LIST:
        return tuple(Measured(item, given.unit, title) for item in given.value)
    return tuple(given.value) if isinstance(given.value, list) else given.value


def value(
    title: str,
    default: Any,
    unit: str = "",
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    choices: Iterable[Any] = (),
    help: str = "",
) -> Any:
    """A parameter of the form, as people type it: a number in unit (its
    limits too), a sweep "start:stop:points", true/false, one of choices, a
    text, a list."""
    name = STATE.name(VALUE, title, len(STATE.values))
    declared = ValueDeclared(
        name, title, default, unit, minimum, maximum, tuple(choices), help
    )
    STATE.values.append(declared)
    STATE.declared()
    if STATE.describing:
        return default
    given = STATE.inputs.values.get(name) if STATE.inputs else None
    if given is None:
        given = _bench().lab.call(ParseValue(value=declared))
    STATE.given[name] = given
    return python_value(given, title)


def plot(
    title: str,
    table: str,
    x: str,
    y: str,
    group_by: Union[str, Iterable[str]] = (),
    kind: str = "line",
    z: Optional[str] = None,
    into: Optional[str] = None,
) -> PlotInfo:
    """A plot of a table the measurement fills, known before it starts;
    curves by the values of group_by. into: a graph of the window (its
    title) it is drawn into, when there is one of the same units; the dock
    of the measurement may choose another."""
    name = STATE.name(PLOT, title, len(STATE.plots))
    grouped = (group_by,) if isinstance(group_by, str) else tuple(group_by)
    declared = PlotInfo(
        key=name, title=title, table=table, x=x, y=y, group_by=grouped,
        kind=kind, z=z, into=into,
    )  # fmt: skip
    STATE.plots.append(declared)
    STATE.declared()
    return declared


def instrument(
    id: str,
    driver: str,
    connection: Union[str, Mapping[str, Any]],
    **quantities: Reading,
) -> RawInstrument:
    """An instrument of the profile by its id there, its driver
    (generic.scpi: one without a driver of its own, raw commands only) and
    how it is reached (tcp://169.254.0.50:5025, prologix://host/19,
    serial://COM3, visa://<resource>; or the fields as the profile holds
    them). Not in the profile yet, or there with another driver or
    connection, it is put there once a person allows it, in the window or
    in this terminal; an agent's script is refused. quantities: names of its
    raw commands, reading(...) and setting(...)."""
    named = named_values(quantities)
    name = STATE.name(INSTRUMENT, id, len(STATE.instruments))
    given = connection if isinstance(connection, str) else dict(connection)
    STATE.instruments.append(InstrumentDeclared(name, id, driver, given))
    STATE.declared()
    if STATE.describing:
        return None
    bench = _bench()
    declare = DeclareInstrument(instrument=id, driver=driver, connection=given)
    try:
        bench.approve(lambda: bench.lab.call(declare))
    except LabError as e:
        if e.code != ErrorCode.DENIED or not agent(bench.origin):
            raise
        raise LabError(
            ErrorCode.DENIED,
            f"{id} ({driver}) is not in the profile as declared, and an"
            " agent's script does not change the profile",
            "a person adds it: runs this script once, or Setup → Add"
            " instrument → Generic (raw) in the ThzDAQ window",
        ) from None
    return RawInstrument(bench, id, named)
