"""Leases: who uses a device and how; only exclusive use conflicts."""

import pytest
from lab_helpers import bodies
from thzdaq_api.devices import DescribeDevice, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import LeasesChanged
from thzdaq_api.leases import EXCLUSIVE, READ, SHARED, ListLeases
from thzdaq_api.measurements import CancelMeasurement, StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import IV_CURVE, MONITOR_TIME
from thzdaq_api.measurement_file import read_measurement
from thzdaq_core.domain.leases import conflicts

# Long enough to be running while the test acts on its devices
SLOW_IV = {
    "voltage": {"start": 0.0, "stop": 5e-3, "points": 2000},
    "settle_time": 0.01,
    "first_point_delay": 0.0,
}


@pytest.mark.parametrize(
    "mode, other, clash",
    [
        (READ, EXCLUSIVE, False),
        (SHARED, SHARED, False),
        (SHARED, EXCLUSIVE, True),
        (EXCLUSIVE, SHARED, True),
        (EXCLUSIVE, EXCLUSIVE, True),
        (EXCLUSIVE, READ, False),
    ],
)
def test_only_exclusive_use_conflicts(mode, other, clash):
    assert conflicts(mode, other) is clash


def finish(lab, run_id):
    lab.call(CancelMeasurement(id=run_id))
    return lab.call(WaitMeasurement(id=run_id, timeout=10))


def iv(share=False):
    return StartMeasurement(
        procedure=IV_CURVE,
        parameters=SLOW_IV,
        devices={"bias": "sis_bias_1"},
        share=share,
    )


def test_a_swept_device_needs_share_and_both_note_it(lab):
    heard = []
    lab.subscribe(heard.append)
    first = lab.call(iv())
    (lease,) = lab.call(ListLeases())
    assert (lease.device, lease.mode, lease.run) == ("sis_bias_1", EXCLUSIVE, first.id)
    set_bias = SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV")
    with pytest.raises(LabError) as caught:
        lab.call(set_bias)
    assert caught.value.code == ErrorCode.CONFLICT and f"#{first.id}" in str(
        caught.value
    )
    with pytest.raises(LabError) as caught:
        lab.call(iv())
    assert caught.value.code == ErrorCode.CONFLICT
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV", share=True))
    second = lab.call(iv(share=True))
    first_file = read_measurement(finish(lab, first.id).path)
    second_file = read_measurement(finish(lab, second.id).path)
    by_first = first_file.metadata["conflicts"]
    assert [entry["by"] for entry in by_first] == ["test", "test"]  # the set, the run
    assert by_first[0]["key"] == "voltage_set" and by_first[1]["run"] == first.id
    assert second_file.metadata["conflicts"][0]["run"] == first.id
    assert lab.call(ListLeases()) == ()
    assert bodies(heard, LeasesChanged)[-1].leases == ()


def test_reading_conflicts_with_nothing_and_notes_what_others_change(lab):
    monitor = lab.call(
        StartMeasurement(
            procedure=MONITOR_TIME,
            parameters={"watch": ["power_meter_1"], "interval": 0.05},
        )
    )
    sweep = lab.call(iv())  # its bias is not the monitor's
    assert {(lease.device, lease.mode) for lease in lab.call(ListLeases())} == {
        ("power_meter_1", READ),
        ("sis_bias_1", EXCLUSIVE),
    }
    quantities = lab.call(DescribeDevice(ref="power_meter_1")).quantities
    settable = next(q for q in quantities if q.settable and q.kind == "float")
    value = settable.minimum if settable.minimum is not None else 1.0
    lab.call(SetQuantity(ref="power_meter_1", key=settable.key, value=value))
    finish(lab, sweep.id)
    noted = read_measurement(finish(lab, monitor.id).path).metadata["interactions"]
    assert noted[0]["key"] == settable.key and noted[0]["by"] == "test"


def test_a_dry_run_checks_like_a_start_and_starts_nothing(lab, tmp_path):
    from thzdaq_api.measurements import PLANNED, ListRuns

    planned = lab.call(
        StartMeasurement(
            procedure=IV_CURVE,
            parameters=SLOW_IV,
            devices={"bias": "sis_bias_1"},
            dry_run=True,
        )
    )
    assert (planned.id, planned.status, planned.total) == (0, PLANNED, 2000)
    assert planned.devices == {"bias": "sis_bias_1"}
    assert lab.call(ListRuns()) == () and lab.call(ListLeases()) == ()
    assert not list((tmp_path / "data").glob("*.json"))
    # What a start refuses, a dry run refuses: a device that does not suit
    with pytest.raises(LabError) as caught:
        lab.call(
            StartMeasurement(
                procedure=IV_CURVE,
                parameters=SLOW_IV,
                devices={"bias": "power_meter_1"},
                dry_run=True,
            )
        )
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "lacks VoltageSource" in str(caught.value)
    # ... and a device another measurement sweeps, unless shared
    first = lab.call(iv())
    with pytest.raises(LabError) as caught:
        lab.call(
            StartMeasurement(
                procedure=IV_CURVE,
                parameters=SLOW_IV,
                devices={"bias": "sis_bias_1"},
                dry_run=True,
            )
        )
    assert caught.value.code == ErrorCode.CONFLICT
    shared = lab.call(
        StartMeasurement(
            procedure=IV_CURVE,
            parameters=SLOW_IV,
            devices={"bias": "sis_bias_1"},
            dry_run=True,
            share=True,
        )
    )
    assert shared.status == PLANNED
    assert [lease.run for lease in lab.call(ListLeases())] == [first.id]
    finish(lab, first.id)


def test_a_run_tells_the_conflicts_it_accepted(lab):
    first = lab.call(iv())
    second = lab.call(iv(share=True))
    (noted,) = second.conflicts
    assert (noted["device"], noted["run"], noted["mode"]) == (
        "sis_bias_1",
        first.id,
        EXCLUSIVE,
    )
    assert finish(lab, first.id).conflicts  # the swept one notes it too
    finish(lab, second.id)


def test_a_profile_edit_waits_for_the_measurements_it_disturbs(lab):
    import copy

    from thzdaq_api.station import GetStation, UpdateStation

    run = lab.call(iv())
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    sis = profile["instruments"]["sis_block_1"]["devices"]["sis_bias_1"]
    sis["settings"] = {"offset_voltage": 1e-4, "offset_current": 0.0}
    with pytest.raises(LabError) as caught:
        lab.call(UpdateStation(profile=profile))
    assert caught.value.code == ErrorCode.NOT_ALLOWED
    assert f"#{run.id}" in str(caught.value) and "sis_bias_1" in str(caught.value)
    # What the measurement does not use changes at once
    edited = copy.deepcopy(lab.call(GetStation()).profile)
    edited["instruments"]["power_meter_1"]["title"] = "IF detector"
    meter = edited["instruments"]["power_meter_1"]
    meter["connection"] = {"kind": "socket", "host": "10.0.0.9", "port": 5025}
    lab.call(UpdateStation(profile=edited))
    finish(lab, run.id)
    lab.call(UpdateStation(profile=profile))  # and the rest once it ended
