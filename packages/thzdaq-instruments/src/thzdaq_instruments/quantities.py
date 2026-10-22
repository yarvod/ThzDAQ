"""Quantities: the values a device part can read or set, with units.

A quantity binds a name and a unit to getter/setter calls of a capability
(voltage of a VoltageSource, power of a PowerDetector, ...). Generic device
controls, monitors and plots are built from them, so a new driver gets a
working UI by implementing capabilities; drivers add their own quantities
(e.g. the short circuit of a SIS bias) with the ``quantities`` class attribute.

Several quantities may come from one call (voltage and current from
measure()): they share a ``source`` and read_values() calls it once.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Tuple

from thzdaq_instruments import capabilities as caps

Kind = Literal["float", "int", "bool", "text"]


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
    field: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()  # allowed values of a "text" quantity
    # Configuration of the instrument (a multiplier, an OEM head) rather than a
    # setpoint: kept in the station profile, never written on connect
    persistent: bool = False

    @property
    def readable(self) -> bool:
        return self.get is not None or self.source is not None

    @property
    def settable(self) -> bool:
        return self.set is not None

    @property
    def label(self) -> str:
        return f"{self.title}, {self.unit}" if self.unit else self.title

    def read(self, target: Any) -> Any:
        if self.source is not None:
            return getattr(self.source(target), self.field)
        if self.get is None:
            raise AttributeError(f"{self.key} is write-only")
        return self.get(target)

    def write(self, target: Any, value: Any) -> Any:
        if self.set is None:
            raise AttributeError(f"{self.key} is read-only")
        return self.set(target, value)


def _measure(target):
    return target.measure()


CAPABILITY_QUANTITIES: Dict[type, Tuple[Quantity, ...]] = {
    caps.Switchable: (
        Quantity(
            "output", "Output", kind="bool",
            get=lambda t: t.get_output(), set=lambda t, v: t.set_output(bool(v)),
        ),
    ),
    caps.VoltageSource: (
        Quantity(
            "voltage_set", "Voltage setpoint", "V",
            get=lambda t: t.get_voltage(), set=lambda t, v: t.set_voltage(float(v)),
        ),
    ),
    caps.CurrentSource: (
        Quantity(
            "current_set", "Current setpoint", "A",
            get=lambda t: t.get_current(), set=lambda t, v: t.set_current(float(v)),
        ),
    ),
    caps.VoltageCurrentMeter: (
        Quantity("voltage", "Voltage", "V", source=_measure, field="voltage"),
        Quantity("current", "Current", "A", source=_measure, field="current"),
    ),
    caps.FrequencySource: (
        Quantity(
            "frequency", "Frequency", "Hz",
            get=lambda t: t.get_frequency(), set=lambda t, v: t.set_frequency(float(v)),
        ),
    ),
    caps.PowerLevel: (
        Quantity(
            "power_level", "Power level", "dBm",
            get=lambda t: t.get_power(), set=lambda t, v: t.set_power(float(v)),
        ),
    ),
    caps.PowerDetector: (
        Quantity("power", "Power", "dBm", get=lambda t: t.read_power()),
    ),
    caps.TunableFilter: (
        Quantity("frequency", "Frequency", "Hz", set=lambda t, v: t.tune(float(v))),
    ),
    caps.Thermometer: (
        Quantity("temperature", "Temperature", "K", get=lambda t: t.read_temperature()),
    ),
    caps.VacuumGauge: (
        Quantity("pressure", "Pressure", "Pa", get=lambda t: t.read_pressure()),
    ),
    caps.Rotator: (
        Quantity(
            "angle", "Angle", "deg",
            get=lambda t: t.get_angle(), set=lambda t, v: t.rotate_to(float(v)),
        ),
    ),
}  # fmt: skip


# Short circuit of a bias or coil output (SIS block)
SHORT = Quantity(
    "short", "Short", kind="bool",
    get=lambda t: t.get_short(), set=lambda t, v: t.set_short(bool(v)),
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


def quantities_for(
    capabilities: Iterable[type], extra: Iterable[Quantity] = ()
) -> List[Quantity]:
    """Quantities of the given capabilities, then the extra (driver) ones."""
    found: Dict[str, Quantity] = {}
    for capability in capabilities:
        for quantity in CAPABILITY_QUANTITIES.get(capability, ()):
            found.setdefault(quantity.key, quantity)
    for quantity in extra:
        found[quantity.key] = quantity
    return list(found.values())


def quantities_of(target: Any) -> List[Quantity]:
    """Quantities of a device part: from its capabilities, then its own ones."""
    if hasattr(target, "target"):  # a port adapter: delegated abilities count too
        capabilities = [c for c in caps.ALL_CAPABILITIES if isinstance(target, c)]
    else:
        capabilities = caps.capabilities_of(type(target))
    extra = getattr(type(target), "quantities", None) or getattr(
        getattr(target, "target", None), "quantities", ()
    )
    return quantities_for(capabilities, extra)


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
            values[quantity.key] = getattr(sources[key], quantity.field)
        else:
            values[quantity.key] = quantity.get(target)
    return values
