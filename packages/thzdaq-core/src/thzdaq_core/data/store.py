"""Datasets on disk as JSON Lines, written while the measurement runs.

    {"type": "header", ...metadata}
    {"type": "record", "stream": "power", "data": {...}}
    ...
    {"type": "footer", "status": "completed", ...}

A crash leaves a valid file without a footer; it reads back as "interrupted".
"""

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from thzdaq_core.data.dataset import INTERRUPTED, Dataset

PathLike = Union[str, Path]
FORMAT = "thzdaq-dataset"
FORMAT_VERSION = 1


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


def dumps(value: Any) -> str:
    return json.dumps(_encode(value), ensure_ascii=False, allow_nan=False)


def loads(text: str) -> Any:
    return _decode(json.loads(text))


class DatasetWriter:
    def __init__(self, path: PathLike, fsync: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fsync = fsync
        self._file = open(self.path, "x", encoding="utf-8")

    def _write(self, line: Dict[str, Any]) -> None:
        self._file.write(dumps(line) + "\n")
        self._file.flush()
        if self.fsync:
            os.fsync(self._file.fileno())

    def write_header(self, dataset: Dataset) -> None:
        self._write(
            {
                "type": "header",
                "format": FORMAT,
                "version": FORMAT_VERSION,
                **dataset.header(),
            }
        )

    def write_record(self, stream: str, record: Dict[str, Any]) -> None:
        self._write({"type": "record", "stream": stream, "data": record})

    def write_footer(self, dataset: Dataset) -> None:
        self._write({"type": "footer", **dataset.footer()})

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def read_dataset(path: PathLike) -> Dataset:
    header: Optional[Dict[str, Any]] = None
    footer: Optional[Dict[str, Any]] = None
    streams: Dict[str, List[Dict[str, Any]]] = {}
    with open(path, encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                item = loads(line)
            except json.JSONDecodeError:
                # Torn last line after a crash; earlier lines are intact
                break
            kind = item.pop("type", None)
            if kind == "header":
                item.pop("format", None)
                item.pop("version", None)
                header = item
            elif kind == "record":
                streams.setdefault(item["stream"], []).append(item["data"])
            elif kind == "footer":
                footer = item
    if header is None:
        raise ValueError(f"{path}: no dataset header")
    dataset = Dataset.from_dict({**header, **(footer or {}), "streams": streams})
    if footer is None:
        dataset.status = INTERRUPTED
    return dataset


class DataStore:
    """Folder of datasets: <root>/<YYYY-MM-DD>/<id>_<procedure>.jsonl"""

    def __init__(self, root: PathLike, fsync: bool = False):
        self.root = Path(root)
        self.fsync = fsync

    def path_for(self, dataset: Dataset) -> Path:
        day = dataset.started[:10]
        procedure = dataset.procedure.replace(".", "_")
        return self.root / day / f"{dataset.id}_{procedure}.jsonl"

    def writer(self, dataset: Dataset) -> DatasetWriter:
        return DatasetWriter(self.path_for(dataset), fsync=self.fsync)

    def paths(self) -> List[Path]:
        return sorted(self.root.glob("*/*.jsonl"))

    def __iter__(self) -> Iterator[Dataset]:
        for path in self.paths():
            yield read_dataset(path)

    def save(self, dataset: Dataset) -> Path:
        """Write a whole finished dataset at once (e.g. imported or edited)."""
        writer = self.writer(dataset)
        try:
            writer.write_header(dataset)
            for stream, records in dataset.streams.items():
                for record in records:
                    writer.write_record(stream, record)
            writer.write_footer(dataset)
        finally:
            writer.close()
        return writer.path
