"""Copies of the profile a workspace keeps, across restarts of the daemon."""

from pathlib import Path

from thzdaq_api.workspace import STATIONS, create
from thzdaq_core.application.workspaces import Workspaces, made


def workspaces(home: Path) -> Workspaces:
    return Workspaces(home, home / "data", lambda folder: None)


def test_a_copy_is_made_when_the_profile_changed_since_the_last(tmp_path):
    create(tmp_path / "w")
    folder = (tmp_path / "w").resolve()
    first = workspaces(tmp_path).copy_profile(folder, "lab", "a: 1\n")
    daemon = workspaces(tmp_path)  # started again: the last copy is on disk
    assert daemon.copy_profile(folder, "lab", "a: 1\n") == first
    second = daemon.copy_profile(folder, "lab", "a: 2\n")
    assert second.file != first.file
    # Back to what an older copy holds: still a new one, the last differs
    third = daemon.copy_profile(folder, "lab", "a: 1\n")
    assert third.file not in (first.file, second.file)
    assert (folder / third.file).read_text() == "a: 1\n"
    assert len(list((folder / STATIONS).iterdir())) == 3


def test_a_copy_removed_by_hand_is_made_again(tmp_path):
    create(tmp_path)
    daemon = workspaces(tmp_path)
    first = daemon.copy_profile(tmp_path, "lab", "a: 1\n")
    (tmp_path / first.file).unlink()
    again = daemon.copy_profile(tmp_path, "lab", "a: 1\n")
    assert (tmp_path / again.file).read_text() == "a: 1\n"


def test_a_folder_without_thzdaq_toml_gets_no_copy(tmp_path):
    assert workspaces(tmp_path).copy_profile(tmp_path, "lab", "a: 1\n") is None
    assert not (tmp_path / STATIONS).exists()


def test_copies_are_ordered_by_when_they_were_made():
    names = [
        "lab@2026-11-04_15-30-12.yaml",
        "lab@2026-11-04_15-30-12+2.yaml",
        "lab@2026-11-04_15-30-12+10.yaml",
        "lab@2026-11-04_15-30-13.yaml",
    ]
    assert sorted(names[::-1], key=lambda name: made(Path(name))) == names
