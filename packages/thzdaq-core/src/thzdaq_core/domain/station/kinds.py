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

from thzdaq_instruments import default_registry
from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.registry import DriverRegistry

from thzdaq_core.domain.errors import ProcedureError, StationError
from thzdaq_core.domain.parameters import FloatParameter, Parameter
from thzdaq_core.domain.station.ports import AttributePort


def instrument_type(driver: str, registry: Optional[DriverRegistry] = None) -> str:
    """rigol.dp832a -> power_supply: instrument ids in profiles name the kind of
    device (power_supply_3, not rigol_dp832a_1); the driver declares it."""
    registry = registry or default_registry()
    if driver in registry and registry.get(driver).device_type:
        return registry.get(driver).device_type
    return driver.split(".")[-1].replace("-", "_")


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
