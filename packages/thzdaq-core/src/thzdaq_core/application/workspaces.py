"""Workspaces: the folders of experiments (thzdaq_api.workspace). A measurement
is written to the data/ of the workspace its client names, the daemon's own
when it names none; the daemon keeps a store per folder, opened when it is
first needed.

Numbers of measurements grow in each folder, and one number names one
measurement of the daemon (a run, its leases, its events): a folder's next is
one more than its largest and than the daemon's last, so its numbers may skip.

The daemon's own folder is the program's: its stations/ holds the profiles of
the bench, and a profile named by its bare name is one of them. A workspace
(a folder with thzdaq.toml) keeps copies of the profile its measurements were
made with in its stations/: <name>@<when>.yaml, a new one only when the
profile changed since the last copy; each measurement notes its copy and hash.
"""

import hashlib
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DATA
from thzdaq_api.workspace import (
    PROFILE_SUFFIX,
    STATIONS,
    ProfileCopy,
    is_workspace,
    profile_path,
)

from thzdaq_core.application.ports import MeasurementRepository

StoreOf = Callable[[Path], MeasurementRepository]  # the store of a data folder
COPY_MARK = "@"  # stations/<name>@<when>.yaml
STAMP = "%Y-%m-%d_%H-%M-%S"  # when a copy was made: allowed in any file name
AGAIN = "+"  # <name>@<when>+2.yaml: the second copy made in that second


class Workspaces:
    def __init__(self, home: Path, data: Path, store_of: StoreOf):
        """home: the daemon's own workspace, its measurements in data."""
        self.home = Path(home).resolve()
        self._store_of = store_of
        self._stores: Dict[Path, MeasurementRepository] = {
            self.home: store_of(Path(data))
        }
        self._copies: Dict[Tuple[Path, str], ProfileCopy] = {}  # the last ones
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

    def profile(self, station: str) -> str:
        """The file of a profile: a bare name is one of the program's."""
        return str(profile_path(self.home, station))

    def copy_profile(self, folder: Path, name: str, text: str) -> Optional[ProfileCopy]:
        """The copy of the profile named name (as its file holds it: text) in
        a workspace: the last one when the profile has not changed since,
        else a new one. None for a folder that is no workspace. OSError when
        it cannot be written."""
        if not is_workspace(folder):
            return None
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._lock:
            last = self._copies.get((folder, name)) or last_copy(folder, name)
            if (
                last is None
                or last.sha256 != digest
                or not (folder / last.file).exists()
            ):
                last = write_copy(folder, name, text, digest)
            self._copies[folder, name] = last
            return last


def made(copy: Path) -> Tuple[str, int]:
    """When a copy was made, for their order: its stamp, then its number."""
    when = copy.stem.rpartition(COPY_MARK)[2]
    stamp, _, number = when.partition(AGAIN)
    return stamp, int(number) if number.isdigit() else 1


def last_copy(folder: Path, name: str) -> Optional[ProfileCopy]:
    """The copy of a profile a workspace got last; None for none."""
    copies = list((folder / STATIONS).glob(f"{name}{COPY_MARK}*{PROFILE_SUFFIX}"))
    if not copies:
        return None
    path = max(copies, key=made)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ProfileCopy(path.relative_to(folder).as_posix(), digest)


def write_copy(folder: Path, name: str, text: str, digest: str) -> ProfileCopy:
    """A new copy, named by when it was made (another one in the same second
    gets a number)."""
    stations = folder / STATIONS
    stations.mkdir(exist_ok=True)
    stem = f"{name}{COPY_MARK}{datetime.now().strftime(STAMP)}"
    path, number = stations / f"{stem}{PROFILE_SUFFIX}", 1
    while path.exists():
        number += 1
        path = stations / f"{stem}{AGAIN}{number}{PROFILE_SUFFIX}"
    path.write_bytes(text.encode("utf-8"))
    return ProfileCopy(path.relative_to(folder).as_posix(), digest)
