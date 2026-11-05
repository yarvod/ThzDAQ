"""The measurement file (thzdaq-measurement v1): what a run produced, as plain
dicts that go to JSON. The daemon writes it; anyone reads it (read_measurement,
MeasurementFolder) and exports a table (export_csv).

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

While it runs, the file holds its description without records (the data of
every table empty) and the records are appended next to it, one line each,
to <id>_<procedure>.jsonl: {"table": "iv", "record": {"voltage": ...}}. At
its end the whole file is written and the records file removed. A file still
marked running (its writer gone, or not finished) reads with the records of
its records file: none of them is lost when the process is killed.
"""

import csv
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

from thzdaq_api.data import decode_values, encode_values

PathLike = Union[str, Path]

FORMAT = "thzdaq-measurement"
FORMAT_VERSION = 1

RUNNING = "running"
COMPLETED = "completed"
CANCELLED = "cancelled"
FAILED = "failed"
INTERRUPTED = "interrupted"  # saved as running, but the process is gone
STATUSES = (RUNNING, COMPLETED, CANCELLED, FAILED, INTERRUPTED)

# Metadata of what others did to its devices: a change of a device it sweeps,
# accepted with share (conflicts), and changes to the devices it only uses
CONFLICTS = "conflicts"
INTERACTIONS = "interactions"
# Metadata of what a person allowed the script that started it in advance
ALLOWED = "allowed"
# Metadata: the copy of the bench profile in its workspace (workspace.ProfileCopy)
PROFILE = "profile"
# Metadata: plots a run added while it ran (a script's m.plot), as PlotInfo
PLOTS = "plots"
# Metadata: the script a session ran, as sessions.ScriptSource (path, sha256, text)
SCRIPT = "script"


# The records of a running measurement, next to its file: one line each
RECORDS_SUFFIX = ".jsonl"
TABLE = "table"
RECORD = "record"

# Numbers given by the store (1, 2, 3, ... per data folder); 0 until numbered.
# Files of older versions keep their text ids ("20261023-022400-ab12").
MeasurementId = Union[int, str]


@dataclass(frozen=True)
class Column:
    key: str
    title: str = ""
    unit: str = ""  # SI unit of the stored values
    # The device quantity the values were read from, "<ref>/<key>"
    # (power_meter_1/power); empty for set, swept or computed values
    source: str = ""

    @property
    def label(self) -> str:
        title = self.title or self.key
        return f"{title}, {self.unit}" if self.unit else title

    def to_dict(self) -> Dict[str, Any]:
        found = {"key": self.key, "title": self.title, "unit": self.unit}
        return {**found, "source": self.source} if self.source else found

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Column":
        return cls(
            data["key"],
            data.get("title", ""),
            data.get("unit", ""),
            data.get("source", ""),
        )


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
        Column("srr_upper", "SRR upper", "dB"),
        Column("srr_lower", "SRR lower", "dB"),
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

    def __getitem__(self, key: str) -> List[Any]:
        """The values of a column: table["voltage"]."""
        return self.data[key]

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

    def describe(self, column: Column) -> None:
        """Another title, unit or source for a column it has."""
        self.columns = [column if c.key == column.key else c for c in self.columns]

    def rows(self) -> Iterator[Dict[str, Any]]:
        keys = list(self.data)
        for values in zip(*(self.data[k] for k in keys)):
            yield dict(zip(keys, values))

    def to_dict(self, records: bool = True) -> Dict[str, Any]:
        """records=False: its description, every column without values."""
        return {
            "title": self.title,
            "columns": [c.to_dict() for c in self.columns],
            "data": self.data if records else {key: [] for key in self.data},
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
    started: str = ""  # ISO time, set by whoever starts it (the runner)
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

    def gather(self, records: Iterable[Tuple[str, Mapping[str, Any]]]) -> None:
        """The records a records file appended (table, record), in order, but
        those it has already: the n-th record of a table is skipped when the
        table holds n or more."""
        held = {name: len(table) for name, table in self.tables.items()}
        counted: Dict[str, int] = {}
        for table, record in records:
            counted[table] = counted.get(table, 0) + 1
            if counted[table] > held.get(table, 0):
                self.append(table, record)

    def finish(self, status: str, at: str, error: Optional[str] = None) -> None:
        """Ended with `status` at the ISO time `at`."""
        if status not in STATUSES:
            raise ValueError(f"Unknown measurement status {status!r}")
        self.status = status
        self.error = error
        self.finished = at

    def to_dict(self, records: bool = True) -> Dict[str, Any]:
        """records=False: its description, as the file of a running one holds
        it (its records are in the records file)."""
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
            "tables": {k: v.to_dict(records) for k, v in self.tables.items()},
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
            started=data.get("started") or "",
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


def dumps(value: Any, indent: Optional[int] = None) -> str:
    return json.dumps(
        encode_values(value), ensure_ascii=False, allow_nan=False, indent=indent
    )


def loads(text: str) -> Any:
    return decode_values(json.loads(text))


def write_file(path: PathLike, text: str) -> Path:
    """Through a temporary file: a crash leaves the previous complete version."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def write_measurement(measurement: Measurement, path: PathLike) -> Path:
    """The whole measurement, records in it (write_file)."""
    return write_file(path, dumps(measurement.to_dict(), indent=1))


def records_path(path: PathLike) -> Path:
    """Where a running measurement appends its records: 000042_monitor_time.jsonl
    next to 000042_monitor_time.json."""
    return Path(path).with_suffix(RECORDS_SUFFIX)


def record_line(table: str, record: Mapping[str, Any]) -> str:
    """A record as its line in a records file."""
    return dumps({TABLE: table, RECORD: record}) + "\n"


def read_records(path: PathLike) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """The records of a records file, in order: (table, record); none when
    there is none. A line cut short (the last one, by a crash while it was
    written) ends them."""
    try:
        file = open(path, "rb")
    except FileNotFoundError:
        return
    with file:
        for line in file:
            try:
                found = loads(line.decode("utf-8"))
            except ValueError:  # JSONDecodeError, UnicodeDecodeError
                return
            yield found[TABLE], found[RECORD]


def read_measurement(path: PathLike) -> Measurement:
    """A measurement file; one still marked running reads as interrupted (its
    writer is gone or has not finished), with the records its records file
    holds. ValueError when it is not one."""
    try:
        data = loads(Path(path).read_text(encoding="utf-8"))
        measurement = Measurement.from_dict(data)
        if measurement.status == RUNNING:
            measurement.status = INTERRUPTED
            measurement.gather(read_records(records_path(path)))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: {e}") from e
    measurement.metadata["path"] = str(path)
    return measurement


def export_csv(measurement: Measurement, table: str, path: PathLike) -> Path:
    """One table as CSV; the header row carries titles with units."""
    data = measurement.tables[table]
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([c.label for c in data.columns])
        keys = [c.key for c in data.columns]
        for row in data.rows():
            writer.writerow([row.get(key) for key in keys])
    return path


def file_id(path: Path) -> Optional[int]:
    """000042_sis_iv_curve.json -> 42; None for files named otherwise."""
    head = path.name.split("_", 1)[0]
    return int(head) if head.isdigit() else None


class MeasurementFolder:
    """A data folder of measurement files: <root>/<YYYY-MM-DD>/<id>_<procedure>.json"""

    def __init__(self, root: PathLike):
        self.root = Path(root)

    def paths(self) -> List[Path]:
        return sorted(self.root.glob("*/*.json"))

    def load(self, path: PathLike) -> Measurement:
        return read_measurement(path)

    def __iter__(self) -> Iterator[Measurement]:
        for path in self.paths():
            try:
                yield read_measurement(path)
            except ValueError:
                continue
