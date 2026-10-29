"""The bench's profile, the drivers a profile can use, the shared connections."""

from typing import Any, Dict, Optional, Tuple, Union

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


class ListConnections(Operation[Tuple[ConnectionInfo, ...]]):
    """Connections the profile's instruments share, and their state."""


class ResetConnection(Operation[bool]):
    """Break and reopen a connection that hangs (its instruments reconnect on
    their next command). Returns whether it was open."""

    rights = Rights.SET
    key: ConnectionKey
