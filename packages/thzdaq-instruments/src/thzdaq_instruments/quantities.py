"""Quantities: the values a device part can read or set, with units.

A quantity binds a name and a unit to getter/setter calls of a capability
(voltage of a VoltageSource, power of a PowerDetector, ...). Generic device
controls, monitors and plots are built from them, so a new driver gets a
working UI by implementing capabilities; drivers add their own quantities
(e.g. the short circuit of a SIS bias) with the ``quantities`` class attribute.

Several quantities may come from one call (voltage and current from
measure()): they share a ``source`` and read_values() calls it once. A
setpoint names the methods that set it (``setters``), so a guarded device
checks and ramps every call that changes it, whoever makes it.
"""

from dataclasses import dataclass, replace
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from thzdaq_instruments import capabilities as caps
from thzdaq_instruments.units import parse_value

Kind = Literal["float", "int", "bool", "text"]


BOOL_WORDS = {
    "true": True,
    "on": True,
    "1": True,
    "false": False,
    "off": False,
    "0": False,
}


def parse_as(spec: Any, value: Any) -> Any:
    """A value as given, as a quantity or an action argument takes it: spec has
    key, kind, unit, choices, minimum and maximum."""
    if spec.kind == "bool":
        if isinstance(value, str):
            word = value.strip().lower()
            if word not in BOOL_WORDS:
                raise ValueError(f"{spec.key}: {value!r} is not on or off")
            return BOOL_WORDS[word]
        return bool(value)
    if spec.kind == "text":
        text = str(value)
        if spec.choices and text not in [str(c) for c in spec.choices]:
            raise ValueError(f"{spec.key}: {text!r} is not one of {list(spec.choices)}")
        return text
    number = parse_value(value, spec.unit) if isinstance(value, str) else value
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        raise ValueError(f"{spec.key}: {value!r} is not a number")
    number = int(number) if spec.kind == "int" else float(number)
    if spec.minimum is not None and number < spec.minimum:
        raise ValueError(f"{spec.key}: {number} is below {spec.minimum}")
    if spec.maximum is not None and number > spec.maximum:
        raise ValueError(f"{spec.key}: {number} is above {spec.maximum}")
    return number


@dataclass(frozen=True)
class Quantity:
    key: str
    title: str
    unit: str = ""  # SI symbol or dBm / deg; display scaling is up to the UI
    kind: Kind = "float"
    get: Optional[Callable[[Any], Any]] = None
    set: Optional[Callable[[Any, Any], Any]] = None
    # Shared call for several quantities, e.g. "measure" -> ChannelReading
    source: Optional[Callable[[Any], Any]] = None
    field: Union[str, int, None] = None  # attribute of the source result, or index
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()  # allowed values of a "text" quantity
    # Configuration of the instrument (a multiplier, an OEM head) rather than a
    # setpoint: kept in the station profile, never written on connect
    persistent: bool = False
    # Methods of the part that set it, the plain one first (it takes the value
    # alone, write() calls it); used instead of set
    setters: Tuple[str, ...] = ()
    danger: str = ""  # what may go wrong when it is set, asked first; empty when safe

    @property
    def readable(self) -> bool:
        return self.get is not None or self.source is not None

    @property
    def settable(self) -> bool:
        return self.set is not None or bool(self.setters)

    @property
    def label(self) -> str:
        return f"{self.title}, {self.unit}" if self.unit else self.title

    def parse(self, value: Any) -> Any:
        """A value as a person or a client gives it, as this quantity takes it:
        "2.3mV" -> 0.0023 for a V quantity, "on" -> True for a bool one."""
        return parse_as(self, value)

    def read(self, target: Any) -> Any:
        if self.source is not None:
            return pick(self.source(target), self.field)
        if self.get is None:
            raise AttributeError(f"{self.key} is write-only")
        return self.get(target)

    def write(self, target: Any, value: Any) -> Any:
        if self.setters:
            return getattr(target, self.setters[0])(self.parse(value))
        if self.set is None:
            raise AttributeError(f"{self.key} is read-only")
        return self.set(target, value)


def pick(result: Any, field: Union[str, int, None]) -> Any:
    """A field of a shared call: an attribute, or an item of a list (None if absent)."""
    if isinstance(field, int):
        return result[field] if field < len(result) else None
    return getattr(result, field)


def _measure(target):
    return target.measure()


def _temperatures(target):
    return target.read_temperatures()


def _pressures(target):
    return target.read_pressures()


# Setpoints of capabilities, named: drivers, limits and procedures refer to them
OUTPUT = Quantity(
    "output",
    "Output",
    kind="bool",
    get=lambda t: t.get_output(),
    setters=("set_output",),
)
VOLTAGE_SET = Quantity(
    "voltage_set",
    "Voltage setpoint",
    "V",
    get=lambda t: t.get_voltage(),
    setters=("set_voltage",),
)
CURRENT_SET = Quantity(
    "current_set",
    "Current setpoint",
    "A",
    get=lambda t: t.get_current(),
    setters=("set_current",),
)
FREQUENCY = Quantity(
    "frequency",
    "Frequency",
    "Hz",
    get=lambda t: t.get_frequency(),
    setters=("set_frequency",),
)
POWER_LEVEL = Quantity(
    "power_level",
    "Power level",
    "dBm",
    get=lambda t: t.get_power(),
    setters=("set_power",),
)
ANGLE = Quantity(
    "angle", "Angle", "deg", get=lambda t: t.get_angle(), setters=("rotate_to",)
)

CAPABILITY_QUANTITIES: Dict[type, Tuple[Quantity, ...]] = {
    caps.Switchable: (OUTPUT,),
    caps.VoltageSource: (VOLTAGE_SET,),
    caps.CurrentSource: (CURRENT_SET,),
    caps.VoltageCurrentMeter: (
        Quantity("voltage", "Voltage", "V", source=_measure, field="voltage"),
        Quantity("current", "Current", "A", source=_measure, field="current"),
    ),
    caps.FrequencySource: (FREQUENCY,),
    caps.PowerLevel: (POWER_LEVEL,),
    caps.PowerDetector: (
        Quantity("power", "Power", "dBm", get=lambda t: t.read_power()),
    ),
    caps.TunableFilter: (
        Quantity("frequency", "Frequency", "Hz", setters=("tune",)),
    ),
    caps.Thermometer: (
        Quantity("temperature", "Temperature", "K", get=lambda t: t.read_temperature()),
    ),
    caps.VacuumGauge: (
        Quantity("pressure", "Pressure", "Pa", get=lambda t: t.read_pressure()),
    ),
    # F-70: discharge, water out, water in (the fourth sensor is spare); return pressure
    caps.Compressor: (
        Quantity("temperature_1", "Discharge temperature", "K", source=_temperatures, field=0),
        Quantity("temperature_2", "Water out temperature", "K", source=_temperatures, field=1),
        Quantity("temperature_3", "Water in temperature", "K", source=_temperatures, field=2),
        Quantity("pressure_1", "Return pressure", "Pa", source=_pressures, field=0),
    ),
    caps.Rotator: (ANGLE,),
}  # fmt: skip


# The bias of a SIS block also takes a voltage corrected by readback
SIS_VOLTAGE_SET = replace(VOLTAGE_SET, setters=("set_voltage", "set_voltage_precise"))


# Coil current the SIS block reports (the setpoint field is what was asked)
COIL_CURRENT = Quantity("coil_current", "Current", "A", get=lambda t: t.read_current())


# A bias or coil output of the SIS block is active when it is not shorted
SHORT = Quantity(
    "active", "Active", kind="bool",
    get=lambda t: not t.get_short(), set=lambda t, v: t.set_short(not v),
    danger="Shorts or opens the output: a step on a biased junction may damage it",
)  # fmt: skip


OEM_STATES = ("OFF", "ON")

# Calibration load (chopper): which load the receiver sees, and whether it spins
CHOPPER_QUANTITIES = (
    Quantity(
        "load_state", "Load", kind="text", choices=("hot", "cold", "between"),
        get=lambda t: t.load_state(),
    ),
    Quantity("running", "Rotating", kind="bool", get=lambda t: t.is_running()),
)  # fmt: skip

POWER_UNITS = ("DBM", "W", "DBUV")

# Configuration of a power meter (R&S NRX): kept in the station profile.
# read_power() is dBm whatever the display unit; the reading is in that unit.
POWER_METER_QUANTITIES = (
    Quantity(
        "reading", "Reading (display unit)", get=lambda t: t.fetch(),
    ),
    Quantity(
        "power_unit", "Display unit", kind="text", choices=POWER_UNITS,
        get=lambda t: t.get_units(), set=lambda t, v: t.set_units(str(v)),
        persistent=True,
    ),
    Quantity(
        "averaging", "Averaging filter", kind="bool",
        get=lambda t: t.get_averaging(), set=lambda t, v: t.set_averaging(bool(v)),
        persistent=True,
    ),
    Quantity(
        "filter_time", "Filter time", "s",
        get=lambda t: t.get_filter_time(),
        set=lambda t, v: t.set_filter_time(float(v)), minimum=0, persistent=True,
    ),
    Quantity(
        "aperture_time", "Aperture time", "s",
        get=lambda t: t.get_aperture_time(),
        set=lambda t, v: t.set_aperture_time(float(v)), minimum=0, persistent=True,
    ),
    Quantity(
        "limit_lower", "Lower limit (display unit)",
        get=lambda t: t.get_lower_limit(),
        set=lambda t, v: t.set_lower_limit(float(v)), persistent=True,
    ),
    Quantity(
        "limit_upper", "Upper limit (display unit)",
        get=lambda t: t.get_upper_limit(),
        set=lambda t, v: t.set_upper_limit(float(v)), persistent=True,
    ),
)  # fmt: skip

# Configuration of a generator: shown in its dock, kept in the station profile
GENERATOR_QUANTITIES = (
    Quantity(
        "frequency_multiplier", "Frequency multiplier",
        get=lambda t: t.get_frequency_multiplier(),
        set=lambda t, v: t.set_frequency_multiplier(float(v)),
        minimum=0.001, maximum=1000, persistent=True,
    ),
    Quantity(
        "oem_state", "OEM head", kind="text", choices=OEM_STATES,
        get=lambda t: t.get_oem_state(), set=lambda t, v: t.set_oem_state(str(v)),
        persistent=True,
    ),
    Quantity(
        "oem_start", "OEM start frequency", "Hz",
        get=lambda t: t.get_oem_frequency_start(),
        set=lambda t, v: t.set_oem_frequency_start(float(v)), persistent=True,
    ),
    Quantity(
        "oem_stop", "OEM stop frequency", "Hz",
        get=lambda t: t.get_oem_frequency_stop(),
        set=lambda t, v: t.set_oem_frequency_stop(float(v)), persistent=True,
    ),
    Quantity(
        "oem_multiplier", "OEM multiplier",
        get=lambda t: t.get_oem_multiplier(),
        set=lambda t, v: t.set_oem_multiplier(float(v)),
        minimum=1, maximum=100, persistent=True,
    ),
)  # fmt: skip


def by_key(
    table: Mapping[type, Iterable[Any]],
    capabilities: Iterable[type],
    extra: Iterable[Any],
) -> List[Any]:
    """What the capabilities give in the table (quantities, actions), then the
    extra (driver) ones; an extra one replaces a capability's with its key."""
    found: Dict[str, Any] = {}
    for capability in capabilities:
        for item in table.get(capability, ()):
            found.setdefault(item.key, item)
    for item in extra:
        found[item.key] = item
    return list(found.values())


def quantities_for(
    capabilities: Iterable[type], extra: Iterable[Quantity] = ()
) -> List[Quantity]:
    """Quantities of the given capabilities, then the extra (driver) ones."""
    return by_key(CAPABILITY_QUANTITIES, capabilities, extra)


def declared(target: Any, attribute: str) -> Tuple[List[type], Tuple[Any, ...]]:
    """Capabilities of a device part and what its class declares under the
    attribute (quantities, actions); a port adapter counts what it delegates."""
    if hasattr(target, "target"):
        capabilities = [c for c in caps.ALL_CAPABILITIES if isinstance(target, c)]
    else:
        capabilities = caps.capabilities_of(type(target))
    own = getattr(type(target), attribute, None) or getattr(
        getattr(target, "target", None), attribute, ()
    )
    return capabilities, tuple(own)


def quantities_of(target: Any) -> List[Quantity]:
    """Quantities of a device part: from its capabilities, then its own ones."""
    return quantities_for(*declared(target, "quantities"))


def read_values(
    target: Any, quantities: Optional[Iterable[Quantity]] = None
) -> Dict[str, Any]:
    """Read every readable quantity, calling a shared source (measure()) once."""
    values: Dict[str, Any] = {}
    sources: Dict[int, Any] = {}
    for quantity in quantities_of(target) if quantities is None else quantities:
        if not quantity.readable:
            continue
        if quantity.source is not None:
            key = id(quantity.source)
            if key not in sources:
                sources[key] = quantity.source(target)
            values[quantity.key] = pick(sources[key], quantity.field)
        else:
            values[quantity.key] = quantity.get(target)
    return values
