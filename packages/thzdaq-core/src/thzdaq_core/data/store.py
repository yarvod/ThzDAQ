"""Measurements on disk: one JSON file each, <root>/<YYYY-MM-DD>/<id>_<procedure>.json

The runner saves at the start, every few seconds while records come and at
the end. Writes go to a temporary file first, so a crash leaves the previous
complete version; a file still marked running reads back as interrupted.
"""

import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union

from thzdaq_core.data.measurement import INTERRUPTED, RUNNING, Measurement

PathLike = Union[str, Path]


def _encode(value: Any) -> Any:
    if isinstance(value, complex):
        return {"__complex__": [value.real, value.imag]}
    if isinstance(value, float) and not math.isfinite(value):
        return {"__float__": repr(value)}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if hasattr(value, "item") and callable(value.item):  # numpy scalars
        return _encode(value.item())
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__complex__"}:
            real, imag = value["__complex__"]
            return complex(real, imag)
        if set(value) == {"__float__"}:
            return float(value["__float__"])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def dumps(value: Any, indent: Optional[int] = None) -> str:
    return json.dumps(
        _encode(value), ensure_ascii=False, allow_nan=False, indent=indent
    )


def loads(text: str) -> Any:
    return _decode(json.loads(text))


def write_json(measurement: Measurement, path: PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dumps(measurement.to_dict(), indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_json(path: PathLike) -> Measurement:
    try:
        data = loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: {e}") from e
    measurement = Measurement.from_dict(data)
    if measurement.status == RUNNING:
        measurement.status = INTERRUPTED
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


class MeasurementStore:
    """Folder of measurement JSON files."""

    def __init__(self, root: PathLike):
        self.root = Path(root)

    def path_for(self, measurement: Measurement) -> Path:
        day = measurement.started[:10]
        procedure = measurement.procedure.replace(".", "_")
        return self.root / day / f"{measurement.id}_{procedure}.json"

    def save(self, measurement: Measurement, path: Optional[PathLike] = None) -> Path:
        path = write_json(measurement, path or self.path_for(measurement))
        measurement.metadata["path"] = str(path)
        return path

    def load(self, path: PathLike) -> Measurement:
        return read_json(path)

    def paths(self) -> List[Path]:
        return sorted(self.root.glob("*/*.json"))

    def __iter__(self) -> Iterator[Measurement]:
        for path in self.paths():
            try:
                yield read_json(path)
            except ValueError:
                continue
