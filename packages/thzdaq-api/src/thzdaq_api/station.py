"""The bench's profile, the drivers a profile can use, the shared connections.

The profile travels as its YAML file holds it (version 2): instruments by id,
each with its driver, title, connection and the devices configured on it.
"""

from typing import Any, Dict, Iterable, Optional, Tuple, Union

import msgspec

from thzdaq_api.measurements import ParameterInfo
from thzdaq_api.operation import Operation, Rights

ConnectionKey = Tuple[Union[str, int, float, None], ...]


class StationProfile(msgspec.Struct, frozen=True):
    """The profile as its YAML file holds it (version 2: instruments with their
    devices), where it is kept, and whether the bench runs on simulators."""

    name: str
    path: Optional[str]
    simulate: bool
    profile: Dict[str, Any]


class DeviceKindInfo(msgspec.Struct, frozen=True):
    """A device a user can configure on an instrument (a SIS bias on a block)."""

    key: str
    title: str
    settings: Tuple[ParameterInfo, ...] = ()
    needs_channel: bool = False
    channels: Tuple[str, ...] = ()  # the channels it may take


class DriverInfo(msgspec.Struct, frozen=True):
    key: str  # what a profile names as driver
    title: str
    type: str  # what device it is: instrument ids start with it
    capabilities: Tuple[str, ...]
    simulated: bool = False  # a simulator of its own, no hardware
    kinds: Tuple[DeviceKindInfo, ...] = ()
    channels: Tuple[str, ...] = ()  # fixed channels: outputs of a supply
    connection: Optional[Dict[str, Any]] = None  # the recommended one


class ConnectionKindInfo(msgspec.Struct, frozen=True):
    """A way to reach an instrument (a TCP socket, a Prologix GPIB adapter): the
    fields of a connection it uses, in form order, and their defaults."""

    key: str
    title: str
    fields: Tuple[str, ...]
    defaults: Dict[str, Any] = {}


class ConnectionInfo(msgspec.Struct, frozen=True):
    """A connection several instruments may share (a Prologix, a socket)."""

    key: ConnectionKey
    label: str
    instruments: Tuple[str, ...]
    open: bool
    broken: bool


class GetStation(Operation[StationProfile]):
    """The profile of the bench: its instruments, their connections and the
    devices configured on them."""


class LoadStation(Operation[StationProfile]):
    """Work with another profile (a YAML file). Refused while measurements
    run."""

    rights = Rights.STATION
    path: str


class NewStation(Operation[StationProfile]):
    """Start an empty profile in a new file and work with it. Refused while
    measurements run."""

    rights = Rights.STATION
    path: str
    title: str


class UpdateStation(Operation[StationProfile]):
    """Replace the profile with an edited one (as get_station gives it); it is
    checked, saved and applied: only instruments whose setup changed reopen."""

    rights = Rights.STATION
    profile: Dict[str, Any]


class ListDrivers(Operation[Tuple[DriverInfo, ...]]):
    """Drivers a profile can name, with the devices each lets a user configure
    and the connection it recommends."""


class ListConnectionKinds(Operation[Tuple[ConnectionKindInfo, ...]]):
    """The kinds of connections an instrument of the profile may use, with the
    fields each one takes."""


class ConnectInstrument(Operation[str]):
    """Open an instrument and ask who it is: returns its identity, or "opened"
    when it cannot tell."""

    instrument: str


class GetSisCalibration(Operation[Dict[str, Any]]):
    """The calibration coefficients of a SIS bias as the profile keeps them, or
    the defaults of its channel. A coefficient is a number or an arithmetic
    expression ("5.47e-9 / 5")."""

    ref: str


class SetSisCalibration(Operation[StationProfile]):
    """Keep the calibration coefficients of a SIS bias in the profile; they are
    checked first. The device's write_calibration action stores them in the
    block."""

    rights = Rights.STATION
    ref: str
    coefficients: Dict[str, Any]


class ListConnections(Operation[Tuple[ConnectionInfo, ...]]):
    """Connections the profile's instruments share, and their state."""


class ResetConnection(Operation[bool]):
    """Break and reopen a connection that hangs (its instruments reconnect on
    their next command). Returns whether it was open."""

    rights = Rights.SET
    key: ConnectionKey


def free_id(taken: Iterable[str], prefix: str) -> str:
    """The first id like power_supply_3 that is not taken."""
    used = set(taken)
    number = 1
    while f"{prefix}_{number}" in used:
        number += 1
    return f"{prefix}_{number}"
