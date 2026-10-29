"""Ports: what the application needs from the outside, as protocols.

Adapters implement them (adapters/json_store.py: MeasurementRepository); the
composition root (a CLI, the GUI session, later the daemon) passes them in.
"""

from pathlib import Path
from typing import Protocol

from thzdaq_core.domain.data.measurement import Measurement


class MeasurementRepository(Protocol):
    """Where measurements are numbered and saved."""

    def next_id(self) -> int:
        ...

    def save(self, measurement: Measurement) -> Path:
        ...
