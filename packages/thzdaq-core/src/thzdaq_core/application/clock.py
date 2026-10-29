"""Wall time of the bench, ISO with milliseconds: when measurements start and end,
when events and notes happen."""

from datetime import datetime


def wall_time() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
