"""Measurements on disk, as the daemon writes them: one JSON file each,
<root>/<YYYY-MM-DD>/<id>_<procedure>.json (thzdaq_api.measurement_file).

Ids are numbers counted per data folder: the next one is one more than the
largest in the file names, so they keep growing across runs of the program.
Start and end times (to the millisecond) are in every file as well.

The runner saves at the start, every few seconds while records come and at
the end. Writes go to a temporary file first, so a crash leaves the previous
complete version; a file still marked running reads back as interrupted.
"""

import os
import threading
from pathlib import Path
from typing import Optional

from thzdaq_api.measurement_file import (
    Measurement,
    MeasurementFolder,
    PathLike,
    dumps,
    file_id,
)


def write_json(measurement: Measurement, path: PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dumps(measurement.to_dict(), indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return path


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
        procedure = measurement.procedure.replace(".", "_")
        number = measurement.id
        name = f"{number:06d}" if isinstance(number, int) else str(number)
        return self.root / day / f"{name}_{procedure}.json"

    def save(self, measurement: Measurement, path: Optional[PathLike] = None) -> Path:
        path = write_json(measurement, path or self.path_for(measurement))
        measurement.metadata["path"] = str(path)
        return path
