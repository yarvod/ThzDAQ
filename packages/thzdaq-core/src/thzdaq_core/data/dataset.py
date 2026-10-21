import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

RUNNING = "running"
COMPLETED = "completed"
CANCELLED = "cancelled"
FAILED = "failed"
INTERRUPTED = "interrupted"  # file without a footer: the process died mid-run
STATUSES = (RUNNING, COMPLETED, CANCELLED, FAILED, INTERRUPTED)


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


@dataclass
class Dataset:
    """One run of a procedure: self-describing metadata plus record streams.

    Records are plain dicts in SI units, grouped in named streams
    (e.g. "power" for raw readings, "noise" for derived Tn).
    """

    procedure: str
    title: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    station: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    started: str = field(default_factory=now)
    finished: Optional[str] = None
    status: str = RUNNING
    error: Optional[str] = None
    comment: str = ""
    streams: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def append(self, stream: str, record: Dict[str, Any]) -> None:
        self.streams.setdefault(stream, []).append(record)

    def records(self, stream: str) -> List[Dict[str, Any]]:
        return self.streams.get(stream, [])

    def column(self, stream: str, key: str) -> List[Any]:
        return [record.get(key) for record in self.records(stream)]

    def finish(self, status: str, error: Optional[str] = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown dataset status {status!r}")
        self.status = status
        self.error = error
        self.finished = now()

    def header(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "procedure": self.procedure,
            "title": self.title,
            "parameters": self.parameters,
            "station": self.station,
            "started": self.started,
            "comment": self.comment,
            "metadata": self.metadata,
        }

    def footer(self) -> Dict[str, Any]:
        return {
            "finished": self.finished,
            "status": self.status,
            "error": self.error,
            "results": self.results,
            # Superset of the header metadata: cleanup errors, traceback, ...
            "metadata": self.metadata,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {**self.header(), **self.footer(), "streams": self.streams}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Dataset":
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})
