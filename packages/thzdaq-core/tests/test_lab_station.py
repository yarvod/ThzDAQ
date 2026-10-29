"""The profile, the drivers and the connections through LocalLab."""

import copy

import pytest
from lab_helpers import bodies
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import StationChanged
from thzdaq_api.measurements import CancelMeasurement, StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import MONITOR_TIME
from thzdaq_api.station import (
    GetStation,
    ListConnections,
    ListDrivers,
    LoadStation,
    NewStation,
    ResetConnection,
    UpdateStation,
)
from thzdaq_core.adapters.yaml_profiles import load_station


def titles(lab):
    return {d.ref: d.title for d in lab.call(ListDevices())}


def test_the_profile_is_shown_as_its_file_holds_it(lab):
    station = lab.call(GetStation())
    assert station.simulate and station.path.endswith("bench.yaml")
    assert station.profile["version"] == 2
    assert "sis_bias_1" in station.profile["instruments"]["sis_block_1"]["devices"]


def test_an_edited_profile_is_saved_applied_and_told(lab):
    heard = []
    lab.subscribe(heard.append)
    station = lab.call(GetStation())
    profile = copy.deepcopy(station.profile)
    profile["instruments"]["power_meter_1"]["title"] = "IF detector"
    lab.call(UpdateStation(profile=profile))
    assert titles(lab)["power_meter_1"] == "IF detector"
    assert (
        load_station(station.path).instruments["power_meter_1"].title == "IF detector"
    )
    assert bodies(heard, StationChanged)[0].path == station.path


def test_a_broken_profile_is_refused(lab):
    before = lab.call(GetStation()).profile
    profile = copy.deepcopy(before)
    devices = profile["instruments"]["sis_block_1"]["devices"]
    devices["power_meter_1"] = devices["sis_bias_1"]  # an id used twice
    with pytest.raises(LabError) as caught:
        lab.call(UpdateStation(profile=profile))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "used twice" in str(caught.value)
    assert lab.call(GetStation()).profile == before  # nothing applied


def test_another_profile_replaces_the_station_unless_measurements_run(lab, tmp_path):
    empty = lab.call(NewStation(path=str(tmp_path / "empty.yaml"), title="empty"))
    assert empty.name == "empty" and not empty.profile.get("instruments")
    assert lab.call(ListDevices()) == ()
    back = lab.call(LoadStation(path=str(tmp_path / "bench.yaml")))
    assert back.name == "2sb" and "sis_bias_1" in titles(lab)
    monitor = lab.call(
        StartMeasurement(
            procedure=MONITOR_TIME,
            parameters={"watch": ["power_meter_1/power"], "interval": 0.05},
        )
    )
    with pytest.raises(LabError) as caught:
        lab.call(LoadStation(path=str(tmp_path / "empty.yaml")))
    assert caught.value.code == ErrorCode.NOT_ALLOWED and f"#{monitor.id}" in str(
        caught.value
    )
    lab.call(CancelMeasurement(id=monitor.id))
    lab.call(WaitMeasurement(id=monitor.id, timeout=10))


def test_drivers_say_what_a_profile_may_hold(lab):
    drivers = {d.key: d for d in lab.call(ListDrivers())}
    supply, block = drivers["rigol.dp832a"], drivers["scontel.sis_block"]
    assert supply.type == "power_supply" and supply.channels == ("1", "2", "3")
    assert supply.connection["kind"] == "socket"
    sis_bias = next(k for k in block.kinds if k.key == "sis_bias")
    assert {s.name for s in sis_bias.settings} == {"offset_voltage", "offset_current"}
    assert drivers["sim.power_supply"].simulated


def test_connections_are_listed_and_reset(lab):
    assert lab.call(ListConnections()) == ()  # simulators share no connection
    assert lab.call(ResetConnection(key=("socket", "10.0.0.1", 1))) is False
