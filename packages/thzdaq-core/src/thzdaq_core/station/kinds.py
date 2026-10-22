"""Kinds of configured devices and how a device object is built.

A configured device is a sub-device a driver declares (SubdeviceType: SIS
bias, SIS coil): the part comes from the instrument accessor and the
settings become attributes of the part (SIS offsets). Each kind declares its
settings as parameters with units, so the Setup form and validation come for
free.

Instruments that are one device (a generator, a power meter) or have fixed
channels (supply outputs) have no kinds; how a measurement uses a channel
(an IF switch, YIG power) is chosen in the measurement.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Type

from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.instrument import Instrument

from thzdaq_core.errors import ProcedureError, StationError
from thzdaq_core.parameters import FloatParameter, Parameter
from thzdaq_core.station.ports import AttributePort

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
    # Instrument accessor of the part and the keys it accepts
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
    return subdevice_kinds(driver_cls)


# Kinds of profile version 2 before they were dropped: what a measurement chooses now
DROPPED_KINDS = ("frequency_multiplier", "sideband_selector", "switch")


def kind_capabilities(kind: DeviceKind, target_cls: Optional[type]) -> Tuple[type, ...]:
    """Capabilities of a device of this kind, known without opening anything."""
    return tuple(capabilities_of(kind.part_class or target_cls))
