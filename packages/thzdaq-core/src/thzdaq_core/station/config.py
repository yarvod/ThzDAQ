"""Station (bench) profile: instruments and the devices they host.

An instrument is a driver plus its connection. What a user operates is a
device: the instrument itself (a generator, a power meter), one of its fixed
channels (supply output CH1) or a configured sub-device (SIS bias on DEV4 with
its offsets and calibration). Configured devices live under their instrument.

Devices are addressed by refs: "power_meter_1", "power_supply_3:1" for a
fixed channel, or the id of a configured device ("sis_bias_1"); ids are
unique within the station.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, Iterator, List, Optional, Tuple

from thzdaq_instruments.transport.base import ConnectionSpec

from thzdaq_core.errors import StationError

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CHANNEL_SEPARATOR = ":"


@dataclass
class DeviceConfig:
    kind: str  # sub-device type of the driver: sis_bias, sis_coil
    channel: Optional[Hashable] = None  # DEV4, supply channel 1; None = the instrument
    title: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)  # offsets, multiplier, ...
    metadata: Dict[str, Any] = field(default_factory=dict)  # calibration, notes


@dataclass
class InstrumentConfig:
    driver: str  # registry key, e.g. "rigol.dp832a"
    connection: Optional[ConnectionSpec] = None
    options: Dict[str, Any] = field(default_factory=dict)  # driver constructor kwargs
    simulate: bool = False
    sim_options: Dict[str, Any] = field(default_factory=dict)  # simulator kwargs
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)  # kept, not passed to driver
    # Configuration set from the dock (frequency multiplier, OEM head): the
    # values last written to the instrument. Never written on connect.
    settings: Dict[str, Any] = field(default_factory=dict)
    devices: Dict[str, DeviceConfig] = field(default_factory=dict)


def channel_ref(instrument_id: str, key: Hashable) -> str:
    return f"{instrument_id}{CHANNEL_SEPARATOR}{key}"


@dataclass
class StationConfig:
    name: str
    instruments: Dict[str, InstrumentConfig] = field(default_factory=dict)
    description: str = ""

    def devices(self) -> Iterator[Tuple[str, str, DeviceConfig]]:
        """(device id, instrument id, config) of every configured device."""
        for instrument_id, instrument in self.instruments.items():
            for device_id, device in instrument.devices.items():
                yield device_id, instrument_id, device

    def find_device(self, device_id: str) -> Optional[Tuple[str, DeviceConfig]]:
        for found_id, instrument_id, device in self.devices():
            if found_id == device_id:
                return instrument_id, device
        return None

    def problems(self) -> List[str]:
        problems = []
        seen: Dict[str, str] = {}
        for instrument_id in self.instruments:
            if not IDENTIFIER.match(instrument_id):
                problems.append(f"instrument id {instrument_id!r} is not an identifier")
            seen[instrument_id] = "instrument"
        for device_id, instrument_id, device in self.devices():
            if not IDENTIFIER.match(device_id):
                problems.append(f"device id {device_id!r} is not an identifier")
            if device_id in seen:
                problems.append(f"id {device_id!r} is used twice")
            seen[device_id] = instrument_id
            if not device.kind:
                problems.append(f"device {device_id!r} has no kind")
        return problems

    def validate(self) -> "StationConfig":
        problems = self.problems()
        if problems:
            raise StationError(f"Station {self.name!r}: " + "; ".join(problems))
        return self

    def next_id(self, prefix: str) -> str:
        """Free id like power_supply_3 or sis_bias_2."""
        taken = set(self.instruments) | {d for d, _, _ in self.devices()}
        number = 1
        while f"{prefix}_{number}" in taken:
            number += 1
        return f"{prefix}_{number}"
