"""Workspaces: the folders of experiments. A folder is a workspace when it
holds thzdaq.toml: its data/ gets the measurements its clients start, its
scripts/ the scripts people write there, its stations/ the copies of the bench
profile it was measured with. thzdaq.toml names the profile the folder
expects (by its name in the program's stations/) and keeps notes.

A client works in the workspace it is given; else in the one the daemon
started its script in (THZDAQ_WORKSPACE); else in the nearest folder from
here up that holds thzdaq.toml, as git finds its repository. With none it
names none, and the daemon writes to its own folder: the program's.

thzdaq.toml is read with tomllib and written from a template of this module,
so its comments stay and the contract needs no TOML writer.
"""

import json
import os
import tomllib
from pathlib import Path
from typing import Optional, Tuple, Union

import msgspec

from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DATA
from thzdaq_api.station import GetStation

FILE = "thzdaq.toml"
SCRIPT_FOLDER = "scripts"  # the scripts people write in a workspace
STATIONS = "stations"  # the program's profiles; in a workspace, their copies
PROFILE_SUFFIX = ".yaml"
WORKSPACE_ENV = "THZDAQ_WORKSPACE"  # the folder the daemon started a script in
NO_PROFILE = "no profile"  # what a daemon without a profile file works with

PathLike = Union[str, Path]

TEMPLATE = """\
# A ThzDAQ workspace: measurements started here go to data/, scripts live in
# scripts/, copies of the bench profile measured with go to stations/.
# thzdaq commands run in this folder (or below it) and the window opened
# here (thzdaq gui) work in it.

# The bench profile this folder expects: its name in the program's stations/
station = {station}

# Notes on the experiment
notes = {notes}

# Folders of scripts besides scripts/ (relative to this folder, or absolute)
script_folders = {script_folders}
"""


class WorkspaceFile(msgspec.Struct, frozen=True):
    """What thzdaq.toml holds."""

    station: str = ""  # the profile it expects, by its name in stations/
    notes: str = ""
    script_folders: Tuple[str, ...] = ()  # besides scripts/

    def text(self) -> str:
        """As thzdaq.toml: JSON strings and arrays of them are TOML too."""
        return TEMPLATE.format(
            station=json.dumps(self.station, ensure_ascii=False),
            notes=json.dumps(self.notes, ensure_ascii=False),
            script_folders=json.dumps(list(self.script_folders), ensure_ascii=False),
        )


class ProfileCopy(msgspec.Struct, frozen=True):
    """The copy of the bench profile a measurement was made with, kept in its
    workspace: its file there (stations/<name>@<when>.yaml) and hash."""

    file: str
    sha256: str


def is_workspace(folder: PathLike) -> bool:
    return (Path(folder) / FILE).is_file()


def find(start: Optional[PathLike] = None) -> Optional[Path]:
    """The nearest workspace from start (this folder) up; None when none."""
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if is_workspace(folder):
            return folder
    return None


def chosen(given: Optional[PathLike] = None) -> Optional[Path]:
    """The workspace of a client: the folder given, else the one the daemon
    started this script in, else the nearest one from here up; None: the
    program's own, where the daemon writes when it is named none."""
    if given:
        return Path(given).expanduser().resolve()
    started_in = os.environ.get(WORKSPACE_ENV)
    if started_in:
        return Path(started_in)
    return find()


def read(folder: PathLike) -> WorkspaceFile:
    """thzdaq.toml of a folder (empty for a folder without it); LabError
    INVALID_ARGUMENTS when it is not TOML or holds a wrong value."""
    path = Path(folder) / FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return WorkspaceFile()
    try:
        return msgspec.convert(tomllib.loads(text), WorkspaceFile)
    except (tomllib.TOMLDecodeError, msgspec.ValidationError) as e:
        raise LabError(
            ErrorCode.INVALID_ARGUMENTS, f"{path}: {e}", "fix it, then go on"
        ) from None


def create(folder: PathLike, station: str = "") -> bool:
    """Make folder a workspace: thzdaq.toml naming the profile it expects, and
    its data/ and scripts/. A thzdaq.toml already there stays; whether it was
    written."""
    folder = Path(folder)
    for part in (DATA, SCRIPT_FOLDER):
        (folder / part).mkdir(parents=True, exist_ok=True)
    if is_workspace(folder):
        return False
    (folder / FILE).write_text(WorkspaceFile(station).text(), encoding="utf-8")
    return True


def script_folders(folder: PathLike) -> Tuple[Path, ...]:
    """Where a folder keeps its scripts: scripts/, then the folders its
    thzdaq.toml adds; LabError for a broken thzdaq.toml."""
    folder = Path(folder)
    added = read(folder).script_folders
    return (folder / SCRIPT_FOLDER, *(folder / Path(f).expanduser() for f in added))


def add_script_folder(folder: PathLike, added: PathLike) -> None:
    """Keep the scripts of another folder in a workspace's thzdaq.toml: by its
    path relative to the workspace when it is inside, else whole. LabError
    for a folder without thzdaq.toml (its folders would be kept nowhere)."""
    folder, added = Path(folder).resolve(), Path(added).resolve()
    kept = _workspace_file(folder)
    if added in (shown.resolve() for shown in script_folders(folder)):
        return
    inside = added.relative_to(folder) if added.is_relative_to(folder) else added
    _write(folder, kept, (*kept.script_folders, inside.as_posix()))


def remove_script_folder(folder: PathLike, removed: PathLike) -> None:
    """Its scripts are no longer shown with the workspace's (they stay)."""
    folder, removed = Path(folder).resolve(), Path(removed).resolve()
    kept = _workspace_file(folder)
    left = tuple(f for f in kept.script_folders if (folder / f).resolve() != removed)
    _write(folder, kept, left)


def _workspace_file(folder: Path) -> WorkspaceFile:
    if not is_workspace(folder):
        raise LabError(
            ErrorCode.INVALID_ARGUMENTS,
            f"{folder} is not a workspace: it has no {FILE}",
            "make one with thzdaq init, or New workspace in the window",
        )
    return read(folder)


def _write(folder: Path, kept: WorkspaceFile, folders: Tuple[str, ...]) -> None:
    changed = msgspec.structs.replace(kept, script_folders=folders)
    (folder / FILE).write_text(changed.text(), encoding="utf-8")


def profile_name(path: PathLike) -> str:
    """How a profile is named in stations/: the name of its file (lab for
    stations/lab.yaml)."""
    return Path(path).stem


def expected_profile(folder: Optional[Path]) -> Optional[str]:
    """The profile a workspace expects; None for none, or no workspace."""
    if folder is None:
        return None
    return read(folder).station or None


def is_profile_name(station: str) -> bool:
    """lab names stations/lab.yaml of the program; lab.yaml, ./lab and
    stations/lab.yaml are paths."""
    given = Path(station)
    return given.name == station and not given.suffix and station not in (".", "..")


def profile_path(home: PathLike, station: str) -> Path:
    """The file of a profile named as thzdaq.toml names it: a bare name is the
    file of that name in stations/ of home (the program's); anything else is
    a path."""
    if is_profile_name(station):
        return Path(home) / STATIONS / f"{station}{PROFILE_SUFFIX}"
    return Path(station).expanduser()


def other_profile(folder: Optional[Path], loaded: Optional[str]) -> Optional[str]:
    """The profile a workspace expects when the daemon works with another
    (loaded: the file of the daemon's, None for none); None when they agree,
    or the folder expects none."""
    if folder is None:
        return None
    expected = read(folder).station
    if not expected or (loaded and profile_name(loaded) == profile_name(expected)):
        return None
    return expected


def profile_warning(lab, folder: Optional[Path]) -> Optional[str]:
    """What a person is told when the workspace expects another profile than
    the daemon's (lab), with how to switch; None when they agree."""
    if folder is None or not read(folder).station:
        return None
    loaded = lab.call(GetStation()).path
    expected = other_profile(folder, loaded)
    if expected is None:
        return None
    return f"{mismatch_text(expected, loaded)}: thzdaq station load {expected}"


def mismatch_text(expected: str, loaded: Optional[str]) -> str:
    """Told to a person whose workspace expects another profile."""
    working = repr(profile_name(loaded)) if loaded else NO_PROFILE
    return (
        f"This workspace expects the profile {expected!r}; "
        f"the daemon works with {working}"
    )
