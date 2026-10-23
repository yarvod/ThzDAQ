"""Measurement DTOs: what a run produced, as plain dicts that go to JSON.

A Measurement holds tables; a table keeps its data column-wise, like the old
store did ({"voltage": [...], "current": [...]}), and describes every column
(title, SI unit), so plots and exports know what they show.

    {
      "format": "thzdaq-measurement", "version": 1,
      "id": 42, "procedure": "sis.iv_curve", "title": "I-V curve",
      "status": "completed", "started": "...", "finished": "...",
      "comment": "", "parameters": {...},
      "devices": {"bias": {"ref": "sis_bias_1", "title": "SIS b1d4", ...}},
      "tables": {"iv": {"title": "I-V", "columns": [{"key": "voltage",
                 "title": "Voltage", "unit": "V"}, ...],
                 "data": {"voltage": [...], "current": [...]}}},
      "results": {...}, "station": {...}, "metadata": {...}
    }
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

FORMAT = "thzdaq-measurement"
FORMAT_VERSION = 1

RUNNING = "running"
COMPLETED = "completed"
CANCELLED = "cancelled"
FAILED = "failed"
INTERRUPTED = "interrupted"  # saved as running, but the process is gone
STATUSES = (RUNNING, COMPLETED, CANCELLED, FAILED, INTERRUPTED)


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


# Numbers given by the store (1, 2, 3, ... per data folder); 0 until numbered.
# Files of older versions keep their text ids ("20261023-022400-ab12").
MeasurementId = Union[int, str]


@dataclass(frozen=True)
class Column:
    key: str
    title: str = ""
    unit: str = ""  # SI unit of the stored values

    @property
    def label(self) -> str:
        title = self.title or self.key
        return f"{title}, {self.unit}" if self.unit else title

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "title": self.title, "unit": self.unit}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Column":
        return cls(data["key"], data.get("title", ""), data.get("unit", ""))


# Titles and units of the usual record keys; procedures may override per key
KNOWN_COLUMNS: Dict[str, Column] = {
    c.key: c
    for c in (
        Column("time", "Time", "s"),
        Column("wall_time", "Wall time"),
        Column("voltage", "Voltage", "V"),
        Column("voltage_set", "Voltage setpoint", "V"),
        Column("current", "Current", "A"),
        Column("coil_current", "Coil current", "A"),
        Column("power", "Power", "dBm"),
        Column("frequency", "Frequency", "Hz"),
        Column("frequency_set", "Frequency setpoint", "Hz"),
        Column("angle", "Angle", "deg"),
        Column("temperature", "Temperature", "K"),
        Column("pressure", "Pressure", "Pa"),
        Column("y_factor", "Y-factor", "dB"),
        Column("noise_temperature", "Noise temperature", "K"),
        Column("amplifier_temperature", "Amplifier noise temperature", "K"),
        Column("magnitude_db", "Magnitude", "dB"),
        Column("phase_mean", "Mean phase", "rad"),
        Column("power_difference", "Power difference", "dB"),
        Column("load", "Load"),
        Column("channel", "IF channel"),
        Column("tone", "Test tone"),
        Column("device", "Device"),
        Column("sis1_voltage", "SIS1 voltage", "V"),
        Column("sis1_current", "SIS1 current", "A"),
        Column("sis2_voltage", "SIS2 voltage", "V"),
        Column("sis2_current", "SIS2 current", "A"),
        Column("sis1_voltage_set", "SIS1 voltage setpoint", "V"),
        Column("sis2_voltage_set", "SIS2 voltage setpoint", "V"),
        Column("tn_upper", "Tn upper", "K"),
        Column("tn_lower", "Tn lower", "K"),
    )
}


def column_for(key: str, overrides: Optional[Mapping[str, Column]] = None) -> Column:
    if overrides and key in overrides:
        return overrides[key]
    if key in KNOWN_COLUMNS:
        return KNOWN_COLUMNS[key]
    return Column(key, key.replace("_", " ").capitalize())


@dataclass
class Table:
    """Records of one kind, stored column-wise."""

    name: str
    title: str = ""
    columns: List[Column] = field(default_factory=list)
    data: Dict[str, List[Any]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(next(iter(self.data.values()), []))

    def column(self, key: str) -> List[Any]:
        return self.data.get(key, [None] * len(self))

    def get_column(self, key: str) -> Optional[Column]:
        return next((c for c in self.columns if c.key == key), None)

    def append(
        self,
        record: Mapping[str, Any],
        overrides: Optional[Mapping[str, Column]] = None,
    ) -> None:
        size = len(self)
        for key in record:
            if key not in self.data:
                self.columns.append(column_for(key, overrides))
                self.data[key] = [None] * size
        for key, values in self.data.items():
            values.append(record.get(key))

    def rows(self) -> Iterator[Dict[str, Any]]:
        keys = list(self.data)
        for values in zip(*(self.data[k] for k in keys)):
            yield dict(zip(keys, values))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "columns": [c.to_dict() for c in self.columns],
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "Table":
        return cls(
            name=name,
            title=data.get("title", ""),
            columns=[Column.from_dict(c) for c in data.get("columns", [])],
            data={k: list(v) for k, v in (data.get("data") or {}).items()},
        )


@dataclass
class DeviceUse:
    """A device a measurement used, as it was configured then."""

    ref: str
    title: str = ""
    instrument: str = ""
    driver: str = ""
    kind: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeviceUse":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Measurement:
    procedure: str
    title: str = ""
    id: MeasurementId = 0
    status: str = RUNNING
    started: str = field(default_factory=now)
    finished: Optional[str] = None
    error: Optional[str] = None
    comment: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    devices: Dict[str, DeviceUse] = field(default_factory=dict)  # by procedure slot
    tables: Dict[str, Table] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    station: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def table(self, name: str, title: str = "") -> Table:
        if name not in self.tables:
            self.tables[name] = Table(name, title)
        return self.tables[name]

    def append(
        self,
        table: str,
        record: Mapping[str, Any],
        overrides: Optional[Mapping[str, Column]] = None,
    ) -> None:
        self.table(table).append(record, overrides)

    def records(self, table: str) -> List[Dict[str, Any]]:
        return list(self.tables[table].rows()) if table in self.tables else []

    def column(self, table: str, key: str) -> List[Any]:
        return self.tables[table].column(key) if table in self.tables else []

    @property
    def size(self) -> int:
        return sum(len(t) for t in self.tables.values())

    def finish(self, status: str, error: Optional[str] = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown measurement status {status!r}")
        self.status = status
        self.error = error
        self.finished = now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "id": self.id,
            "procedure": self.procedure,
            "title": self.title,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "comment": self.comment,
            "parameters": self.parameters,
            "devices": {k: v.to_dict() for k, v in self.devices.items()},
            "tables": {k: v.to_dict() for k, v in self.tables.items()},
            "results": self.results,
            "station": self.station,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Measurement":
        if data.get("format", FORMAT) != FORMAT:
            raise ValueError(f"not a ThzDAQ measurement: {data.get('format')!r}")
        return cls(
            procedure=data["procedure"],
            title=data.get("title", ""),
            id=data.get("id") or 0,
            status=data.get("status", COMPLETED),
            started=data.get("started") or now(),
            finished=data.get("finished"),
            error=data.get("error"),
            comment=data.get("comment", ""),
            parameters=dict(data.get("parameters") or {}),
            devices={
                k: DeviceUse.from_dict(v)
                for k, v in (data.get("devices") or {}).items()
            },
            tables={
                k: Table.from_dict(k, v) for k, v in (data.get("tables") or {}).items()
            },
            results=dict(data.get("results") or {}),
            station=dict(data.get("station") or {}),
            metadata=dict(data.get("metadata") or {}),
        )
