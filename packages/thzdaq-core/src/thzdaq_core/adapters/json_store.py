"""Measurements on disk: one JSON file each, <root>/<YYYY-MM-DD>/<id>_<procedure>.json

Ids are numbers counted per data folder: the next one is one more than the
largest in the file names, so they keep growing across runs of the program.
Start and end times (to the millisecond) are in every file as well.

The runner saves at the start, every few seconds while records come and at
the end. Values are encoded as thzdaq_api.data says (complex numbers, NaN).
Writes go to a temporary file first, so a crash leaves the previous
complete version; a file still marked running reads back as interrupted.
"""

import csv
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union

from thzdaq_api.data import decode_values, encode_values

from thzdaq_core.domain.data.measurement import INTERRUPTED, RUNNING, Measurement

PathLike = Union[str, Path]


def dumps(value: Any, indent: Optional[int] = None) -> str:
    return json.dumps(
        encode_values(value), ensure_ascii=False, allow_nan=False, indent=indent
    )


def loads(text: str) -> Any:
    return decode_values(json.loads(text))


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


def file_id(path: Path) -> Optional[int]:
    """000042_sis_iv_curve.json -> 42; None for files named otherwise."""
    head = path.name.split("_", 1)[0]
    return int(head) if head.isdigit() else None


class MeasurementStore:
    """Folder of measurement JSON files."""

    def __init__(self, root: PathLike):
        self.root = Path(root)
        self._last = 0
        self._lock = threading.Lock()

    def next_id(self) -> int:
        """A number larger than every measurement in the folder and given so far."""
        with self._lock:
            found = [file_id(path) for path in self.paths()]
            self._last = max([self._last, *(i for i in found if i is not None)]) + 1
            return self._last

    def path_for(self, measurement: Measurement) -> Path:
        """data/<day it started>/<number>_<procedure>.json"""
        if not measurement.started:
            raise ValueError(
                "a measurement has no file before it starts (no start time)"
            )
        day = measurement.started[:10]
        procedure = measurement.procedure.replace(".", "_")
        number = measurement.id
        name = f"{number:06d}" if isinstance(number, int) else str(number)
        return self.root / day / f"{name}_{procedure}.json"

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
