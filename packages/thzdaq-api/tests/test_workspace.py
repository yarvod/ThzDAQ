from pathlib import Path

import pytest
from thzdaq_api import workspace
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DATA
from thzdaq_api.workspace import (
    FILE,
    SCRIPT_FOLDER,
    WORKSPACE_ENV,
    WorkspaceFile,
    chosen,
    create,
    find,
    other_profile,
    profile_path,
    read,
)


@pytest.fixture(autouse=True)
def no_script_workspace(monkeypatch):
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)


def test_create_makes_a_workspace_and_keeps_its_file(tmp_path):
    assert create(tmp_path, "lab")
    assert (tmp_path / DATA).is_dir() and (tmp_path / SCRIPT_FOLDER).is_dir()
    assert read(tmp_path) == WorkspaceFile(station="lab")

    assert not create(tmp_path, "other")
    assert read(tmp_path).station == "lab"


def test_the_file_reads_back_what_was_written(tmp_path):
    written = WorkspaceFile(station='a "b" \\ c', notes="Смесь\nвторая строка\t!")
    (tmp_path / FILE).write_text(written.text(), encoding="utf-8")
    assert read(tmp_path) == written


def test_a_folder_without_the_file_expects_nothing(tmp_path):
    assert read(tmp_path) == WorkspaceFile()
    assert workspace.expected_profile(tmp_path) is None
    assert workspace.expected_profile(None) is None


@pytest.mark.parametrize("text", ["station = ", "station = 3"])
def test_a_broken_file_is_told(tmp_path, text):
    (tmp_path / FILE).write_text(text, encoding="utf-8")
    with pytest.raises(LabError) as e:
        read(tmp_path)
    assert e.value.code == ErrorCode.INVALID_ARGUMENTS
    assert FILE in str(e.value)


def test_the_workspace_is_found_up_from_here(tmp_path, monkeypatch):
    create(tmp_path / "experiment")
    below = tmp_path / "experiment" / "scripts" / "deeper"
    below.mkdir(parents=True)
    assert find(below) == (tmp_path / "experiment").resolve()
    assert find(tmp_path) is None

    monkeypatch.chdir(below)
    assert chosen() == (tmp_path / "experiment").resolve()


def test_a_folder_given_comes_first_then_the_scripts(tmp_path, monkeypatch):
    create(tmp_path / "found")
    monkeypatch.chdir(tmp_path / "found")
    assert chosen(tmp_path / "given") == (tmp_path / "given").resolve()
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "started"))
    assert chosen() == tmp_path / "started"


def test_no_workspace_names_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert chosen() is None


@pytest.mark.parametrize(
    "station, path",
    [
        ("lab", "home/stations/lab.yaml"),
        ("lab.yaml", "lab.yaml"),
        ("stations/lab", "stations/lab"),
        ("/benches/lab.yaml", "/benches/lab.yaml"),
    ],
)
def test_a_bare_name_is_a_profile_of_the_program(station, path):
    assert profile_path(Path("home"), station) == Path(path)


def test_another_profile_than_the_workspace_expects_is_told(tmp_path):
    create(tmp_path, "lab")
    assert other_profile(tmp_path, "/program/stations/lab.yaml") is None
    assert other_profile(tmp_path, "/program/stations/2sb.yaml") == "lab"
    assert other_profile(tmp_path, None) == "lab"
    assert other_profile(None, "/program/stations/2sb.yaml") is None
    told = workspace.mismatch_text("lab", "/program/stations/2sb.yaml")
    assert "'lab'" in told and "'2sb'" in told


def test_a_workspace_without_a_profile_expects_any(tmp_path):
    create(tmp_path)
    assert other_profile(tmp_path, "/program/stations/2sb.yaml") is None


def test_an_older_file_with_script_folders_reads_still(tmp_path):
    (tmp_path / FILE).write_text('station = "lab"\nscript_folders = ["more"]\n')
    assert read(tmp_path) == WorkspaceFile(station="lab")
