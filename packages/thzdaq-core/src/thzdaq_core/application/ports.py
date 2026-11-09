"""Ports: what the application needs from the outside, as protocols.

Adapters implement them (json_store.MeasurementStore: MeasurementRepository,
its RunningFile: MeasurementWriter,
yaml_profiles.YamlProfiles: ProfileRepository, processes.Processes: Launcher;
the daemon's process: DaemonControl); the composition root (a CLI, the GUI
session, the daemon) passes them in.
"""

from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple

from thzdaq_api.daemon import ClientInfo, DaemonSettings, ProcessInfo

from thzdaq_api.measurement_file import Measurement
from thzdaq_core.domain.station.config import StationConfig


class MeasurementWriter(Protocol):
    """The file of a measurement while it runs. A failed write does not stop
    the measurement: the writer tells it in the log."""

    def append(self, table: str, record: Mapping[str, Any]) -> None:
        """A record the measurement took (into its table already): on disk
        when this returns, so a killed process loses none."""

    def update(self) -> None:
        """What else changed (comment, metadata, plots, results) into the file."""

    def close(self) -> None:
        """The whole measurement as it ended, in one file."""


class MeasurementRepository(Protocol):
    """Where measurements are numbered and saved."""

    def next_id(self) -> int:
        ...

    def open(self, measurement: Measurement) -> MeasurementWriter:
        """The file of a measurement that starts now (path_for), written as
        it runs."""

    def save(self, measurement: Measurement, path: Optional[str] = None) -> Path:
        """The whole measurement to its file (path_for), or to path."""

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
        removed: Sequence[str] = (),
    ) -> Launched:
        """command run in folder with these variables added and the removed
        ones left out, its output into log; OSError when it cannot start."""
