"""Devices of the bench: what they are, what they read and what can be set."""

from typing import Dict, Optional, Tuple, Union

import msgspec

from thzdaq_api.operation import Operation, Rights

Value = Union[bool, int, float, str, None]


class QuantityInfo(msgspec.Struct, frozen=True):
    """A value a device reads or takes, in SI units (power in dBm, angles in deg)."""

    key: str
    title: str
    unit: str = ""
    kind: str = "float"  # float, int, bool or text
    readable: bool = True
    settable: bool = False
    persistent: bool = False  # configuration of the instrument, kept in the profile
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[str, ...] = ()  # the values a text quantity takes


class DeviceInfo(msgspec.Struct, frozen=True):
    """A device: an instrument, its fixed channel or a device configured on it."""

    ref: str  # the id measurements and operations name it by
    title: str
    instrument: str  # the instrument it is or belongs to
    kind: str  # instrument, channel, or the configured kind (sis_bias)
    type: str  # what device it is: the configured kind, else the instrument's type
    capabilities: Tuple[str, ...]
    channel: Optional[str] = None
    configured: bool = False


class DeviceDescription(msgspec.Struct, frozen=True):
    device: DeviceInfo
    quantities: Tuple[QuantityInfo, ...]


class Reading(msgspec.Struct, frozen=True):
    ref: str
    values: Dict[str, Value]


class QuantityValue(msgspec.Struct, frozen=True):
    ref: str
    key: str
    value: Value


class Poll(msgspec.Struct, frozen=True):
    id: int  # to cancel it
    ref: str
    interval: float


class ListDevices(Operation[Tuple[DeviceInfo, ...]]):
    """Every device of the bench: its instruments, their fixed channels and the
    devices configured on them (a SIS bias on a SIS block)."""


class DescribeDevice(Operation[DeviceDescription]):
    """A device with its quantities: what it reads and what can be set, with
    units and limits."""

    ref: str


class ReadDevice(Operation[Reading]):
    """Read a device: every readable quantity, or the listed keys. Values are
    in SI units (power in dBm)."""

    ref: str
    keys: Optional[Tuple[str, ...]] = None


class SetQuantity(Operation[QuantityValue]):
    """Set a quantity of a device. A number is in SI units; a text may carry
    its unit ("2.3mV", "223 GHz"); switches take true or false. Returns the
    value set, in SI units. A device a running measurement sweeps is refused
    (conflict) unless share is true; the measurements using it record the
    change."""

    rights = Rights.SET
    ref: str
    key: str
    value: Union[bool, int, float, str]
    share: bool = False


class SubscribePoll(Operation[Poll]):
    """Read a device every `interval` seconds (all readable quantities, or the
    listed keys); readings come as values events. The daemon polls a device
    once, at the shortest interval its subscribers ask for."""

    ref: str
    interval: float
    keys: Optional[Tuple[str, ...]] = None


class CancelPoll(Operation[None]):
    """Stop a poll started by subscribe_poll."""

    id: int
