"""Workspaces: the copies of the profile they keep, profiles by their names
(contract: LocalLab and RemoteLab)."""

import hashlib
import shutil

import pytest
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import PROFILE, read_measurement
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import IV_CURVE
from thzdaq_api.station import GetStation, LoadStation, UpdateStation
from thzdaq_api.workspace import STATIONS, create

QUICK_IV = dict(
    procedure=IV_CURVE,
    parameters={
        "voltage": {"start": 0.0, "stop": 1e-3, "points": 3},
        "settle_time": 0.0,
        "first_point_delay": 0.0,
    },
    devices={"bias": "sis_bias_1"},
)


def measured(lab, folder, **given):
    started = lab.call(StartMeasurement(**QUICK_IV, workspace=str(folder), **given))
    if started.id == 0:  # a dry run
        return started
    return lab.call(WaitMeasurement(id=started.id, timeout=10))


def noted(run):
    return read_measurement(run.path).metadata.get(PROFILE)


def copies(folder):
    return sorted(path.name for path in (folder / STATIONS).glob("*"))


def test_a_workspace_keeps_the_profile_its_measurements_were_made_with(lab, tmp_path):
    folder = tmp_path / "experiment"
    create(folder, "bench")
    first = measured(lab, folder)
    (copy,) = copies(folder)
    assert copy.startswith("bench@") and copy.endswith(".yaml")
    data = (folder / STATIONS / copy).read_bytes()
    assert noted(first) == {
        "file": f"{STATIONS}/{copy}",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    assert b"Sideband separating SIS mixer bench" in data

    # The same profile: the same copy
    second = measured(lab, folder)
    assert noted(second) == noted(first) and copies(folder) == [copy]

    # An edited one: a new copy, the old one stays
    profile = lab.call(GetStation()).profile
    lab.call(UpdateStation(profile={**profile, "description": "after the fix"}))
    third = measured(lab, folder)
    assert len(copies(folder)) == 2 and noted(third) != noted(first)
    assert b"after the fix" in (folder / noted(third)["file"]).read_bytes()


def test_only_a_workspace_keeps_copies(lab, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert noted(measured(lab, plain)) is None
    assert not (plain / STATIONS).exists()
    # The daemon's own folder holds the program's profiles: no copies there
    assert noted(measured(lab, tmp_path)) is None


def test_a_dry_run_copies_nothing(lab, tmp_path):
    create(tmp_path / "experiment")
    measured(lab, tmp_path / "experiment", dry_run=True)
    assert not (tmp_path / "experiment" / STATIONS).exists()


def test_a_profile_is_named_by_its_name_in_the_programs_stations(lab, tmp_path):
    (tmp_path / STATIONS).mkdir()
    shutil.copy(lab.call(GetStation()).path, tmp_path / STATIONS / "other.yaml")
    loaded = lab.call(LoadStation(path="other"))
    assert loaded.path == str((tmp_path / STATIONS / "other.yaml").resolve())
    with pytest.raises(LabError) as caught:
        lab.call(LoadStation(path="missing"))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "missing.yaml" in str(caught.value)
