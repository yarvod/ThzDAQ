"""The profile, the drivers and the connections through LocalLab; an
instrument a script declares goes into the profile once a person allows it."""

import copy
from pathlib import Path

import pytest
from lab_helpers import Window, bodies, calling
from thzdaq_api.devices import ListDevices, RawCommand
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import StationChanged
from thzdaq_api.measurements import CancelMeasurement, StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import MONITOR_TIME
from thzdaq_api.origins import GUI, script
from thzdaq_api.station import (
    ADDED,
    GENERIC,
    KEPT,
    UPDATED,
    ConnectInstrument,
    DeclareInstrument,
    GetSisCalibration,
    GetStation,
    ListConnectionKinds,
    ListConnections,
    ListDrivers,
    LoadStation,
    NewStation,
    ResetConnection,
    SetSisCalibration,
    UpdateStation,
)
from thzdaq_core.adapters.yaml_profiles import load_station, versions


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


def test_connection_kinds_name_their_fields(lab):
    kinds = {k.key: k for k in lab.call(ListConnectionKinds())}
    assert kinds["prologix"].fields[:3] == ("host", "port", "gpib")
    assert kinds["socket"].defaults["timeout"] == 2.0
    assert "gpib" not in kinds["socket"].fields


def test_an_instrument_is_opened_and_says_who_it_is(lab):
    assert "SimSisBlock" in lab.call(ConnectInstrument(instrument="sis_block_1"))
    with pytest.raises(LabError) as error:
        lab.call(ConnectInstrument(instrument="sis_block_9"))
    assert error.value.code == ErrorCode.NOT_FOUND


def test_a_sis_calibration_is_checked_and_kept_in_the_profile(lab):
    defaults = lab.call(GetSisCalibration(ref="sis_bias_1"))
    assert defaults["CurrentMonitorResistance"] == 20  # of DEV4
    with pytest.raises(LabError) as error:
        lab.call(SetSisCalibration(ref="sis_bias_1", coefficients={"VoltageStep": 1}))
    assert error.value.code == ErrorCode.INVALID_ARGUMENTS
    changed = {**defaults, "VoltageStep": "1e-5 / 2"}
    station = lab.call(SetSisCalibration(ref="sis_bias_1", coefficients=changed))
    devices = station.profile["instruments"]["sis_block_1"]["devices"]
    stored = devices["sis_bias_1"]["metadata"]["calibration_coefficients"]
    assert stored["VoltageStep"] == "1e-5 / 2"  # the expression as it was typed
    assert lab.call(GetSisCalibration(ref="sis_bias_1")) == stored
    with pytest.raises(LabError) as error:
        lab.call(GetSisCalibration(ref="power_supply_1:1"))
    assert error.value.code == ErrorCode.NOT_ALLOWED


GAUGE = "gauge_1"
AT = "tcp://169.254.0.50:5025"


def gauge(connection=AT, driver="generic.scpi"):
    return DeclareInstrument(instrument=GAUGE, driver=driver, connection=connection)


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def test_a_persons_script_adds_an_instrument_once_allowed(lab, lab_as, window):
    path = lab.call(GetStation()).path
    itself = lab_as(script("degas"), "script")
    thread, done = calling(itself, gauge())
    approval = window.asked()
    assert approval.title == f"{GAUGE} · add to the profile"
    assert f"{GAUGE} (generic.scpi, {AT}) to the profile 2sb" in approval.text
    window.answer(allowed=True)
    thread.join(5)
    assert done["result"] == ADDED
    saved = load_station(path).instruments[GAUGE]
    assert (saved.driver, saved.connection.host, saved.connection.port) == (
        "generic.scpi", "169.254.0.50", 5025,
    )  # fmt: skip
    assert not saved.title and not saved.devices  # only how it is reached
    assert len(versions(path)) == 1  # the profile before it, kept
    found = {d.ref: d for d in lab.call(ListDevices())}[GAUGE]
    assert found.type == GENERIC and found.raw
    assert (
        "SimGenericScpi"
        in itself.call(RawCommand(instrument=GAUGE, command="*IDN?")).answer
    )


def test_an_instrument_declared_as_the_profile_has_it_asks_nobody(lab, lab_as, window):
    assert lab.call(gauge()) == ADDED  # a person: not asked
    path = lab.call(GetStation()).path
    kept = len(versions(path))
    for origin in (script("degas"), script("degas", by_agent=True)):
        same = gauge({"kind": "socket", "host": "169.254.0.50", "port": 5025})
        assert lab_as(origin, "script").call(same) == KEPT
    assert not window.waiting() and len(versions(path)) == kept


def test_another_address_is_asked_and_refused_leaves_the_profile(lab, lab_as, window):
    lab.call(gauge())
    before = lab.call(GetStation()).profile
    thread, done = calling(
        lab_as(script("degas"), "script"), gauge("tcp://10.0.0.7:5025")
    )
    approval = window.asked()
    assert approval.title == f"{GAUGE} · change in the profile"
    assert approval.text.endswith(f"{AT} → generic.scpi, tcp://10.0.0.7:5025")
    window.answer(allowed=False, text="wrong gauge")
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    assert lab.call(GetStation()).profile == before
    assert lab.call(gauge("tcp://10.0.0.7:5025")) == UPDATED  # a person changes it


def test_an_agents_script_never_changes_the_profile(lab, lab_as, window):
    agents = lab_as(script("degas", by_agent=True), "script")
    with pytest.raises(LabError) as refused:
        agents.call(gauge())
    assert refused.value.code == ErrorCode.DENIED and not window.waiting()
    assert GAUGE not in lab.call(GetStation()).profile["instruments"]


@pytest.mark.parametrize(
    "declared, told",
    [
        (gauge("169.254.0.50:5025"), "is no connection"),
        (gauge(driver="acme.gauge"), "No driver 'acme.gauge'"),
        (
            DeclareInstrument(
                instrument="sis_bias_1", driver="generic.scpi", connection=AT
            ),
            "used twice",
        ),
    ],
)
def test_what_the_profile_cannot_take_is_refused_before_asking(
    lab_as, window, declared, told
):
    with pytest.raises(LabError) as refused:
        lab_as(script("degas"), "script").call(declared)
    assert refused.value.code == ErrorCode.INVALID_ARGUMENTS and told in str(
        refused.value
    )
    assert not window.waiting()


def test_a_profile_keeps_its_earlier_versions(lab, monkeypatch):
    from thzdaq_core.adapters import yaml_profiles

    monkeypatch.setattr(yaml_profiles, "KEPT", 2)
    station = lab.call(GetStation())
    for title in ("one", "two", "three"):
        profile = copy.deepcopy(station.profile)
        profile["instruments"]["power_meter_1"]["title"] = title
        lab.call(UpdateStation(profile=profile))
    lab.call(UpdateStation(profile=profile))  # the same: nothing written
    kept = versions(station.path)
    assert len(kept) == 2 and kept[0].parent == Path(station.path).parent / ".history"
    assert load_station(kept[-1]).instruments["power_meter_1"].title == "two"
