"""Kinds of configured devices and how a device object is built.

Two families:
- sub-devices a driver declares (SubdeviceType: SIS bias, SIS coil): the part
  comes from the instrument accessor; settings become attributes of the part;
- adapters over the instrument or a fixed channel (frequency multiplier,
  sideband selector, switch): settings become adapter arguments.

Every kind declares its settings as parameters with units, so the Setup
form and validation come for free.
"""

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Optional, Tuple, Type

from thzdaq_instruments.capabilities import (
    FrequencySource,
    Switchable,
    capabilities_of,
)
from thzdaq_instruments.instrument import Instrument

from thzdaq_core.errors import ProcedureError, StationError
from thzdaq_core.parameters import BoolParameter, FloatParameter, Parameter
from thzdaq_core.station.ports import (
    DEVICE_PROTOCOLS,
    AttributePort,
    ScaledFrequencySource,
    SidebandSelector,
    SwitchPort,
)

# Instrument ids name the kind of device: power_supply_3, not rigol_dp832a_1
INSTRUMENT_TYPES = {
    "keithley.2200": "power_supply",
    "rigol.dp832a": "power_supply",
    "rs.hmp2030": "power_supply",
    "sim.power_supply": "power_supply",
    "agilent.e8247c": "signal_generator",
    "sim.signal_generator": "signal_generator",
    "rs.nrx": "power_meter",
    "sim.power_meter": "power_meter",
    "scontel.sis_block": "sis_block",
    "sim.sis_block": "sis_block",
    "ni.yig": "yig_filter",
    "sim.yig_filter": "yig_filter",
    "chopper.modbus": "chopper",
    "sim.chopper": "chopper",
    "rs.zva67": "vna",
    "sim.network_analyzer": "vna",
    "rs.fsek30": "spectrum_analyzer",
    "sim.spectrum_analyzer": "spectrum_analyzer",
    "lakeshore.336": "temperature_controller",
    "sim.temperature_controller": "temperature_controller",
    "srs.sr830": "lock_in",
    "sumitomo.f70": "compressor",
    "sumitomo.f70_rest": "compressor",
    "sim.compressor": "compressor",
    "pfeiffer.tc110": "turbo_pump",
    "pfeiffer.gauge": "vacuum_gauge",
    "sim.vacuum_gauge": "vacuum_gauge",
    "arduino.grid": "grid",
    "sim.rotator": "grid",
}


def instrument_type(driver: str) -> str:
    return INSTRUMENT_TYPES.get(driver) or driver.split(".")[-1].replace("-", "_")


def _named(name: str, parameter: Parameter) -> Parameter:
    parameter.name = name
    return parameter


@dataclass(frozen=True)
class DeviceKind:
    key: str
    title: str
    settings: Tuple[Parameter, ...] = ()
    # Adapter kinds: factory(part, **settings) and what the part must offer
    adapter: Optional[Callable[..., Any]] = None
    requires: Tuple[Type, ...] = ()
    # Sub-device kinds: instrument accessor and the keys it accepts
    accessor: Optional[str] = None
    keys: Tuple[Any, ...] = ()
    part_class: Optional[type] = None
    needs_channel: bool = False

    def defaults(self) -> Dict[str, Any]:
        return {p.name: p.default for p in self.settings}

    def clean(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Settings with defaults filled in, validated; raises StationError."""
        known = {p.name: p for p in self.settings}
        unknown = set(settings) - set(known)
        if unknown:
            raise StationError(f"{self.title}: unknown settings {sorted(unknown)}")
        values = self.defaults()
        for name, value in settings.items():
            try:
                values[name] = known[name].validate(value)
            except ProcedureError as e:
                raise StationError(f"{self.title}: {name}: {e}") from None
        return values

    def build(self, part: Any, settings: Dict[str, Any]) -> Any:
        values = self.clean(settings)
        if self.adapter is not None:
            return self.adapter(part, **values)
        return AttributePort(part, values) if values else part


# Settings of driver sub-devices, by sub-device key
SUBDEVICE_SETTINGS: Dict[str, Tuple[Parameter, ...]] = {
    "sis_bias": (
        _named("offset_voltage", FloatParameter(
            "Offset voltage", default=0.0, unit="V", display_unit="mV", display_scale=1e-3,
        )),
        _named("offset_current", FloatParameter(
            "Offset current", default=0.0, unit="A", display_unit="uA", display_scale=1e-6,
        )),
    ),
}  # fmt: skip

ADAPTER_KINDS: Dict[str, DeviceKind] = {
    "frequency_multiplier": DeviceKind(
        "frequency_multiplier",
        "Frequency multiplier",
        settings=(
            _named(
                "multiplier", FloatParameter("Multiplier", default=1.0, minimum=1e-9)
            ),
        ),
        adapter=ScaledFrequencySource,
        requires=(FrequencySource,),
    ),
    "sideband_selector": DeviceKind(
        "sideband_selector",
        "IF sideband switch",
        settings=(
            _named(
                "upper_when_on", BoolParameter("Upper sideband when on", default=True)
            ),
        ),
        adapter=SidebandSelector,
        requires=(Switchable,),
    ),
    "switch": DeviceKind(
        "switch",
        "Switch",
        settings=(_named("inverted", BoolParameter("Inverted", default=False)),),
        adapter=SwitchPort,
        requires=(Switchable,),
    ),
}


def subdevice_kinds(driver_cls: Type[Instrument]) -> Dict[str, DeviceKind]:
    return {
        key: DeviceKind(
            key,
            sub.title,
            settings=SUBDEVICE_SETTINGS.get(key, ()),
            accessor=sub.accessor,
            keys=sub.keys,
            part_class=sub.part_class,
            needs_channel=True,
        )
        for key, sub in driver_cls.subdevices.items()
    }


def kinds_for(driver_cls: Type[Instrument]) -> Dict[str, DeviceKind]:
    """Device kinds a user can add to an instrument of this driver."""
    kinds = subdevice_kinds(driver_cls)
    own = set(capabilities_of(driver_cls))
    channel = (
        set(capabilities_of(driver_cls.channel_class))
        if driver_cls.fixed_channels()
        else set()
    )
    for key, kind in ADAPTER_KINDS.items():
        on_instrument = set(kind.requires) <= own
        on_channel = set(kind.requires) <= channel
        if on_instrument or on_channel:
            # On a supply the switch sits on a channel; on a generator on the instrument
            kinds[key] = replace(
                kind,
                needs_channel=not on_instrument,
                keys=driver_cls.fixed_channels() if on_channel else (),
            )
    return kinds


def kind_capabilities(kind: DeviceKind, target_cls: Optional[type]) -> Tuple[type, ...]:
    """Capabilities of a device of this kind, known without opening anything."""
    found = list(capabilities_of(kind.part_class or target_cls))
    if kind.adapter is not None:
        found += [c for c in capabilities_of(kind.adapter) if c not in found]
        found += [p for p in DEVICE_PROTOCOLS if issubclass(kind.adapter, p)]
    return tuple(found)
