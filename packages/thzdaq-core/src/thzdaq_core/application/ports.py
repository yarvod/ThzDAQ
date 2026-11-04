"""Ports: what the application needs from the outside, as protocols.

Adapters implement them (json_store.MeasurementStore: MeasurementRepository,
yaml_profiles.YamlProfiles: ProfileRepository, processes.Processes: Launcher;
the daemon's process: DaemonControl); the composition root (a CLI, the GUI
session, the daemon) passes them in.
"""

from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence, Tuple

from thzdaq_api.daemon import ClientInfo, DaemonSettings, ProcessInfo

from thzdaq_api.measurement_file import Measurement
from thzdaq_core.domain.station.config import StationConfig


class MeasurementRepository(Protocol):
    """Where measurements are numbered and saved."""

    def next_id(self) -> int:
        ...

    def save(self, measurement: Measurement, path: Optional[str] = None) -> Path:
        """To its file (path_for), or to path."""

    def load(self, path: str) -> Measurement:
        """ValueError when it is no measurement file."""


class ProfileRepository(Protocol):
    """Where station profiles are kept."""

    def load(self, path: str) -> StationConfig:
        ...

    def save(self, config: StationConfig, path: str) -> None:
        ...

    def text(self, config: StationConfig) -> str:
        """The profile as its file holds it (a workspace keeps a copy)."""


class DaemonControl(Protocol):
    """The process the use cases run in: what it is, who listens, its end."""

    def process(self) -> ProcessInfo:
        ...

    def clients(self) -> Tuple[ClientInfo, ...]:
        ...

    def stop(self, restart: bool) -> None:
        """End the process once the current operation has answered; restart:
        start it again with the same profile."""

    def settings(self) -> DaemonSettings:
        ...

    def change(self, settings: DaemonSettings) -> None:
        """Take these settings now and keep them for the next starts."""

    def log(self, lines: int) -> Tuple[str, ...]:
        """The last lines of its log; none without a log file."""


class Launched(Protocol):
    """A process started apart (a script the daemon runs)."""

    pid: int

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """Its exit code once it ended; None when it runs after timeout."""

    def terminate(self) -> None:
        """End it at once."""


class Launcher(Protocol):
    """Starts processes apart from the daemon's terminal."""

    def launch(
        self,
        command: Sequence[str],
        folder: Path,
        environment: Mapping[str, str],
        log: Path,
    ) -> Launched:
        """command run in folder with these variables added, its output into
        log; OSError when it cannot start."""
