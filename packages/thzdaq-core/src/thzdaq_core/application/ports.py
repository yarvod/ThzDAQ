"""Ports: what the application needs from the outside, as protocols.

Adapters implement them (json_store.MeasurementStore: MeasurementRepository,
its RunningFile: MeasurementWriter,
yaml_profiles.YamlProfiles: ProfileRepository, processes.Processes: Launcher,
library.FolderLibrary: Library, instrument_states.JsonInstrumentStates:
InstrumentStates; the daemon's process: DaemonControl); the composition root (a CLI, the GUI
session, the daemon) passes them in.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple

from thzdaq_api.custom import Declarations
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


@dataclass(frozen=True)
class LibraryFile:
    """A script of the bench's library: its name (the file's without .py),
    its file, text and hash."""

    name: str
    path: str
    text: str
    sha256: str


class DescribeFailed(Exception):
    """A script that could not be described: why, with its traceback."""


class Library(Protocol):
    """The bench's own measurements: the scripts of a folder (measurements/
    of the program's)."""

    folder: Path

    def files(self) -> Tuple[LibraryFile, ...]:
        """The scripts there now, by name."""

    def file(self, name: str, text: str) -> LibraryFile:
        """A script of that name with this text, saved or not."""

    def write(self, name: str, text: str) -> LibraryFile:
        """The script saved: a new one, or over the one of that name."""

    def describe(self, file: LibraryFile) -> Declarations:
        """What the script's text declares at its top, as its process tells
        when it runs described (next to the scripts, as they run);
        DescribeFailed when it cannot be."""


class InstrumentStates(Protocol):
    """What the program keeps of instruments between its starts (a grid's
    angle: application.kept), a record per instrument id. Moves come from
    several threads (a run, a dock): a record is kept whole or not at all."""

    def get(self, instrument_id: str) -> Optional[Mapping[str, Any]]:
        """The record kept last; None when there is none."""

    def put(self, instrument_id: str, record: Mapping[str, Any]) -> None:
        """Keep the record (JSON values) at once; a failure to keep it is
        logged, never raised: it must not stop what moves the instrument."""
