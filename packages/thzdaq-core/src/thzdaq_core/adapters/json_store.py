"""Measurements on disk, as the daemon writes them: one JSON file each,
<root>/<YYYY-MM-DD>/<id>_<procedure>.json (thzdaq_api.measurement_file), the
procedure's name with _ for what a file name may not hold.

Ids are numbers counted per data folder: the next one is one more than the
largest in the file names, so they keep growing across runs of the program.
Start and end times (to the millisecond) are in every file as well.

While a measurement runs (RunningFile), its file holds its description
without records, written again only when it changes, and its records are
appended to the records file next to it, a line each; at its end the whole
file is written and the records file removed. A long monitor appends a line
per record instead of writing megabytes every few seconds. Writes of the file
go to a temporary file first, so a crash leaves the previous complete
version; a file still marked running reads back as interrupted, with the
records of its records file.
"""

import logging
import os
import re
import threading
from pathlib import Path
from typing import IO, Any, Dict, Mapping, Optional, Tuple

from thzdaq_api.measurement_file import (
    RUNNING,
    Column,
    Measurement,
    MeasurementFolder,
    PathLike,
    dumps,
    file_id,
    record_line,
    records_path,
    write_file,
    write_measurement,
)

logger = logging.getLogger(__name__)

# What a file name of every system allows of a procedure's name: letters,
# digits, _ and -; a script's "script:<title>" has a colon (a stream of a
# file on NTFS) and may have a slash (a folder)
UNSAFE = re.compile(r"[^\w-]+")


class MeasurementStore(MeasurementFolder):
    """A folder of measurement files the daemon numbers and writes."""

    def __init__(self, root: PathLike):
        super().__init__(root)
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
        procedure = UNSAFE.sub("_", measurement.procedure)
        number = measurement.id
        name = f"{number:06d}" if isinstance(number, int) else str(number)
        return self.root / day / f"{name}_{procedure}.json"

    def open(self, measurement: Measurement) -> "RunningFile":
        return RunningFile(self, measurement, self.path_for(measurement))

    def save(self, measurement: Measurement, path: Optional[PathLike] = None) -> Path:
        """The whole measurement; one that ended needs its records file no
        more (a file left by a crash is gathered so)."""
        path = write_measurement(measurement, path or self.path_for(measurement))
        measurement.metadata["path"] = str(path)
        if measurement.status != RUNNING:
            records_path(path).unlink(missing_ok=True)
        return path


Shape = Tuple[str, Tuple[Column, ...]]  # a table as its description has it


class RunningFile:
    """The file of a running measurement (MeasurementWriter): its description
    when it starts and whenever it changes, a line in the records file per
    record, the whole file at its end.

    A line is flushed as it is written, so it is the operating system's once
    append returns; update puts the lines on the drive itself. A table or a
    column the description lacks is described before its record is appended,
    so every line has its column titles and units. When a line cannot be
    written, the records file stops and every update writes the whole file,
    as before records files."""

    def __init__(self, store: MeasurementStore, measurement: Measurement, path: Path):
        self.store = store
        self.measurement = measurement
        self.path = path
        self._description = ""  # as the file holds it
        self._shapes: Dict[str, Shape] = {}
        self._records: Optional[IO[str]] = None
        measurement.metadata["path"] = str(path)
        self._describe()
        try:
            self._records = open(
                records_path(path), "w", encoding="utf-8", newline="\n"
            )
        except OSError:
            logger.exception(f"{path}: no records file, the whole file is saved")

    def append(self, table: str, record: Mapping[str, Any]) -> None:
        if self._records is None:
            return  # update saves the whole file
        if self._shape(table) != self._shapes.get(table):
            self._describe()
        try:
            self._records.write(record_line(table, record))
            self._records.flush()
        except OSError:
            logger.exception(f"{self.path}: records stop, the whole file is saved")
            self._stop_records()
            self._save()

    def update(self) -> None:
        if self._records is None:
            self._save()
            return
        self._describe()
        try:
            os.fsync(self._records.fileno())
        except OSError:
            logger.exception(f"{self.path}: records not synced")

    def close(self) -> None:
        self._stop_records()
        self._save()

    def _shape(self, table: str) -> Shape:
        found = self.measurement.tables[table]
        return found.title, tuple(found.columns)

    def _describe(self) -> None:
        """Its description, when it is not the file's already (one that
        failed is tried again by the next update, not by every record)."""
        text = dumps(self.measurement.to_dict(records=False), indent=1)
        if text == self._description:
            return
        self._shapes = {name: self._shape(name) for name in self.measurement.tables}
        try:
            write_file(self.path, text)
        except OSError:
            logger.exception(f"{self.path}: description not saved")
            return
        self._description = text

    def _save(self) -> None:
        try:
            self.store.save(self.measurement, self.path)
        except OSError:
            logger.exception(f"{self.path}: not saved")

    def _stop_records(self) -> None:
        if self._records is None:
            return
        records, self._records = self._records, None
        try:
            records.close()
        except OSError:
            logger.exception(f"{self.path}: records file not closed")
