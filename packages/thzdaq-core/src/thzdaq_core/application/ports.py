"""Ports: what the application needs from the outside, as protocols.

Adapters implement them (json_store.MeasurementStore: MeasurementRepository,
yaml_profiles.YamlProfiles: ProfileRepository); the composition root (a CLI,
the GUI session, the daemon) passes them in.
"""

from pathlib import Path
from typing import Protocol

from thzdaq_core.domain.data.measurement import Measurement
from thzdaq_core.domain.station.config import StationConfig


class MeasurementRepository(Protocol):
    """Where measurements are numbered and saved."""

    def next_id(self) -> int:
        ...

    def save(self, measurement: Measurement) -> Path:
        ...


class ProfileRepository(Protocol):
    """Where station profiles are kept."""

    def load(self, path: str) -> StationConfig:
        ...

    def save(self, config: StationConfig, path: str) -> None:
        ...
