"""The workspace of a window: the folder whose data/ gets the measurements it
starts (thzdaq_api.workspace). A window opens the default one, the program's
folder unless a person made another folder the default; a person opens others
(the recent ones are remembered) or makes a new one (thzdaq.toml, data/,
scripts/). Several windows in several folders are several clients of one
daemon."""

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_api import workspace
from thzdaq_api.measurements import DATA
from thzdaq_api.workspace import SCRIPT_FOLDER, expected_profile

from thzdaq_gui.settings import (
    DEFAULT_WORKSPACE,
    RECENT_WORKSPACES,
    app_dir,
    settings,
)

RECENT = 10  # folders remembered


def default_workspace() -> Path:
    """The folder a window opens at start: the one a person made the default
    (while it exists), else the program's."""
    chosen = settings().value(DEFAULT_WORKSPACE)
    if chosen and Path(chosen).is_dir():
        return Path(chosen)
    return app_dir()


class Workspace(QObject):
    changed = Signal()  # another folder: its measurements, its profile

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.folder = Path(folder).resolve()

    @property
    def data(self) -> Path:
        """Where its measurements go."""
        return self.folder / DATA

    @property
    def name(self) -> str:
        return self.folder.name or str(self.folder)

    @property
    def scripts(self) -> Path:
        """Where its scripts of its own go (the bench's own measurements are
        the program's)."""
        return self.folder / SCRIPT_FOLDER

    def holds(self, folder: Optional[str]) -> bool:
        """Whether a measurement made in folder is one of this workspace's."""
        return folder is not None and Path(folder).resolve() == self.folder

    def expected_profile(self) -> Optional[str]:
        """The profile it expects (thzdaq.toml); LabError for a broken file."""
        return expected_profile(self.folder)

    def open(self, folder) -> None:
        folder = Path(folder).resolve()
        self._remember(folder)
        if folder != self.folder:
            self.folder = folder
            self.changed.emit()

    @staticmethod
    def create(folder, station: str) -> None:
        """Make folder a workspace expecting the profile station (open it
        after)."""
        workspace.create(folder, station)

    def recent(self) -> List[Path]:
        """Folders opened lately that still exist, the last first."""
        kept = settings().value(RECENT_WORKSPACES, [], type=list)
        return [Path(folder) for folder in kept if Path(folder).is_dir()]

    def _remember(self, folder: Path) -> None:
        kept = [str(folder)] + [str(f) for f in self.recent() if f != folder]
        settings().setValue(RECENT_WORKSPACES, kept[:RECENT])

    # The default: what a window opens at start
    def is_default(self) -> bool:
        return default_workspace().resolve() == self.folder

    def make_default(self, on: bool) -> None:
        """This folder opens at start; off: the program's again."""
        if on:
            settings().setValue(DEFAULT_WORKSPACE, str(self.folder))
        else:
            settings().remove(DEFAULT_WORKSPACE)
