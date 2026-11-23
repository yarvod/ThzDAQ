"""The fast I-V curve through LocalLab: the bias block sweeps and reads every
point itself, guarded as a whole before it starts."""

import copy

import pytest
from lab_helpers import bodies, wait_for
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import MeasurementProgress, MeasurementRecords
from thzdaq_api.measurements import (
    CancelMeasurement,
    DescribeProcedure,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE_FAST
from thzdaq_api.station import GetStation, UpdateStation

SWEEP = {
    "voltage": {"start": 0.0, "stop": 2e-3, "points": 5},
    "dwell": 1e-3,
    "first_point_delay": 0.0,
}


def start(lab, parameters=SWEEP):
    return lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE_FAST,
            parameters=parameters,
            devices={"bias": "sis_bias_1"},
        )
    )


def ended(lab, run_id):
    info = lab.call(WaitMeasurement(id=run_id, timeout=10))
    assert info.status != "running"
    return info


def rows(heard):
    return [row for batch in bodies(heard, MeasurementRecords) for row in batch.rows]


def test_it_needs_a_bias_that_sweeps_by_itself(lab):
    info = lab.call(DescribeProcedure(procedure=CURRENT_VS_VOLTAGE_FAST))
    (slot,) = info.slots
    assert slot.name == "bias" and "VoltageSweep" in slot.capabilities
    assert "I-V" in {p.title for p in info.plots}
    dwell = next(p for p in info.parameters if p.name == "dwell")
    assert (dwell.unit, dwell.display_unit, dwell.default) == ("s", "ms", 2e-3)


def test_one_point_is_no_sweep(lab):
    one = {**SWEEP, "voltage": {"start": 0.0, "stop": 0.0, "points": 1}}
    with pytest.raises(LabError) as error:
        start(lab, one)
    assert error.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "two points" in error.value.message


def test_every_point_the_block_reads_is_recorded(lab):
    heard = []
    lab.subscribe(heard.append)
    done = ended(lab, start(lab).id)
    assert done.status == "completed" and done.done == done.total == 5
    voltages = [row["voltage"] for row in rows(heard)]
    assert voltages == pytest.approx([0, 0.5e-3, 1e-3, 1.5e-3, 2e-3], abs=1e-5)
    assert all(row["current"] > 0 for row in rows(heard)[1:])


def test_a_cancel_stops_the_sweep(lab):
    heard = []
    lab.subscribe(heard.append)
    long = {**SWEEP, "voltage": {"start": 0.0, "stop": 2e-3, "points": 5000}}
    run = start(lab, long)
    wait_for(lambda: len(bodies(heard, MeasurementProgress)) >= 3)
    lab.call(CancelMeasurement(id=run.id))
    assert ended(lab, run.id).status == "cancelled"
    assert len(rows(heard)) < 5000


def test_a_step_above_the_bench_step_is_refused_before_any_point(lab):
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"limits": {"sis_bias_1": {"voltage_set": {"step": 0.1e-3}}}}
    lab.call(UpdateStation(profile=profile))
    heard = []
    lab.subscribe(heard.append)
    done = ended(lab, start(lab).id)  # its step is 0.5 mV
    assert done.status == "failed" and "bench step" in done.error
    assert rows(heard) == []
