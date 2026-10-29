"""What the bench tells its clients as it happens, numbered.

A client takes a snapshot (GetSnapshot: the values known now and the number of
the last event), then listens from that number; one that fell behind the
daemon's buffer gets Resync and takes a new snapshot.
"""

from typing import Dict, Union

import msgspec

from thzdaq_api.devices import Value
from thzdaq_api.operation import Operation


class QuantitySet(msgspec.Struct, tag="quantity_set", frozen=True):
    """A quantity was set: by whom, from what (if known) to what."""

    ref: str
    key: str
    value: Value
    before: Value = None
    origin: str = ""


class Values(msgspec.Struct, tag="values", frozen=True):
    """Readings of a polled device."""

    ref: str
    values: Dict[str, Value]


class ReadFailed(msgspec.Struct, tag="read_failed", frozen=True):
    """A polled device did not answer or failed."""

    ref: str
    message: str


class Resync(msgspec.Struct, tag="resync", frozen=True):
    """Events were lost: take a new snapshot."""


Body = Union[QuantitySet, Values, ReadFailed, Resync]


class Event(msgspec.Struct, frozen=True):
    seq: int
    at: str  # wall time, ISO
    body: Body


class Snapshot(msgspec.Struct, frozen=True):
    seq: int  # the last event it includes; listen from here
    values: Dict[str, Dict[str, Value]]  # last known values by device and key


class GetSnapshot(Operation[Snapshot]):
    """What the bench knows now (the last values of every device read or set)
    and the number of the last event, to listen from."""
