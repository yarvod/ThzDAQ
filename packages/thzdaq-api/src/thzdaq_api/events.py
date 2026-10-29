"""What the bench tells its clients as it happens, numbered.

A client takes a snapshot (GetSnapshot: the values known now and the number of
the last event), then listens from that number; one that fell behind the
daemon's buffer gets Resync and takes a new snapshot.
"""

from typing import Any, Dict, Optional, Tuple, Union

import msgspec

from thzdaq_api.devices import Value
from thzdaq_api.leases import LeaseInfo
from thzdaq_api.measurements import PlotInfo, RunInfo
from thzdaq_api.operation import Operation


class QuantitySet(msgspec.Struct, tag="quantity_set", frozen=True):
    """A quantity was set: by whom, from what (if known) to what."""

    ref: str
    key: str
    value: Value
    before: Value = None
    origin: str = ""


class ActionDone(msgspec.Struct, tag="action_done", frozen=True):
    """A device did an action (turned to the hot load): by whom, with what."""

    ref: str
    action: str
    arguments: Dict[str, Value]
    origin: str = ""


class Values(msgspec.Struct, tag="values", frozen=True):
    """Readings of a polled device."""

    ref: str
    values: Dict[str, Value]


class ReadFailed(msgspec.Struct, tag="read_failed", frozen=True):
    """A polled device did not answer or failed."""

    ref: str
    message: str


class MeasurementStarted(msgspec.Struct, tag="measurement_started", frozen=True):
    """A measurement started; plots: those it will fill, to show at once."""

    run: RunInfo
    plots: Tuple[PlotInfo, ...]


class MeasurementRecords(msgspec.Struct, tag="measurement_records", frozen=True):
    """Records of a running measurement, a few at a time. Values are encoded as
    in measurement files: thzdaq_api.data.decode_values gives them back."""

    id: int
    table: str
    rows: Tuple[Dict[str, Any], ...]


class MeasurementProgress(msgspec.Struct, tag="measurement_progress", frozen=True):
    id: int
    done: int
    total: Union[int, None] = None


class MeasurementLog(msgspec.Struct, tag="measurement_log", frozen=True):
    id: int
    message: str


class MeasurementFinished(msgspec.Struct, tag="measurement_finished", frozen=True):
    run: RunInfo


class StationChanged(msgspec.Struct, tag="station_changed", frozen=True):
    """The profile changed (edited, or another loaded): devices may differ."""

    name: str
    path: Union[str, None]


class LeasesChanged(msgspec.Struct, tag="leases_changed", frozen=True):
    """A measurement took or gave back its devices: every lease now."""

    leases: Tuple[LeaseInfo, ...]


class Resync(msgspec.Struct, tag="resync", frozen=True):
    """Events were lost: take a new snapshot."""


Body = Union[
    QuantitySet,
    ActionDone,
    Values,
    ReadFailed,
    MeasurementStarted,
    MeasurementRecords,
    MeasurementProgress,
    MeasurementLog,
    MeasurementFinished,
    StationChanged,
    LeasesChanged,
    Resync,
]


def run_id(body: Body) -> Optional[int]:
    """The number of the measurement an event tells about; None for another."""
    if isinstance(body, (MeasurementStarted, MeasurementFinished)):
        return body.run.id
    if isinstance(body, (MeasurementRecords, MeasurementProgress, MeasurementLog)):
        return body.id
    return None


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
