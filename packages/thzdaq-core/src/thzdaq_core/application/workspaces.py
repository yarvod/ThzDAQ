"""Workspaces: the folders of experiments. A measurement is written to the
data/ of the workspace its client names, the daemon's own when it names none;
the daemon keeps a store per folder, opened when it is first needed.

Numbers of measurements grow in each folder, and one number names one
measurement of the daemon (a run, its leases, its events): a folder's next is
one more than its largest and than the daemon's last, so its numbers may skip.
"""

import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.ports import MeasurementRepository

DATA = "data"  # where a workspace keeps its measurements

StoreOf = Callable[[Path], MeasurementRepository]  # the store of a data folder


class Workspaces:
    def __init__(self, home: Path, data: Path, store_of: StoreOf):
        """home: the daemon's own workspace, its measurements in data."""
        self.home = Path(home).resolve()
        self._store_of = store_of
        self._stores: Dict[Path, MeasurementRepository] = {
            self.home: store_of(Path(data))
        }
        self._lock = threading.Lock()

    def folder(self, workspace: Optional[str]) -> Path:
        """The folder a client names, the daemon's own for none."""
        if workspace is None:
            return self.home
        folder = Path(workspace).expanduser().resolve()
        if not folder.is_dir():
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"No workspace {workspace!r}: not a folder",
                "name an existing folder; its data/ gets the measurements",
            )
        return folder

    def store(self, folder: Path) -> MeasurementRepository:
        with self._lock:
            if folder not in self._stores:
                self._stores[folder] = self._store_of(folder / DATA)
            return self._stores[folder]
