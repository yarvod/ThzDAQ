"""Procedures and measurements through LocalLab."""

from pathlib import Path

import pytest
from lab_helpers import bodies
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import (
    MeasurementFinished,
    MeasurementProgress,
    MeasurementRecords,
    MeasurementStarted,
)
from thzdaq_api.measurements import (
    CancelMeasurement,
    DescribeProcedure,
    ListProcedures,
    ListRuns,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.procedures import IV_CURVE, MONITOR_TIME, PV_CURVE

FAST_IV = {
    "voltage": {"start": 0.0, "stop": 2e-3, "points": 11},
    "settle_time": 0.0,
    "first_point_delay": 0.0,
}
MONITOR = {"watch": ["power_meter_1/power"], "interval": 0.02, "duration": 0.0}


def ended(lab, run_id):
    info = lab.call(WaitMeasurement(id=run_id, timeout=10))
    assert info.status != "running"
    return info


def test_procedures_are_listed_and_described(lab):
    assert {IV_CURVE, MONITOR_TIME} <= {p.name for p in lab.call(ListProcedures())}
    info = lab.call(DescribeProcedure(procedure=IV_CURVE))
    voltage = next(p for p in info.parameters if p.name == "voltage")
    assert (voltage.kind, voltage.unit, voltage.display_unit) == ("sweep", "V", "mV")
    assert voltage.default == {"start": 0.0, "stop": 7e-3, "points": 351}
    assert [(s.name, s.kind) for s in info.slots] == [("bias", "sis_bias")]
    assert "VoltageSource" in info.slots[0].capabilities
    assert "I-V" in {p.title for p in info.plots}


def test_slots_follow_the_parameters(lab):
    plain = lab.call(DescribeProcedure(procedure=PV_CURVE))
    hot_cold = lab.call(
        DescribeProcedure(procedure=PV_CURVE, parameters={"hot_cold": True})
    )
    assert "load" not in {s.name for s in plain.slots}
    assert "load" in {s.name for s in hot_cold.slots}


def test_a_measurement_runs_and_is_heard(lab):
    heard = []
    lab.subscribe(heard.append)
    run = lab.call(
        StartMeasurement(
            procedure=IV_CURVE,
            parameters=FAST_IV,
            devices={"bias": "sis_bias_1"},
            comment="contract",
        )
    )
    assert run.status == "running" and run.origin == "test"
    assert run.devices == {"bias": "sis_bias_1"} and run.comment == "contract"
    done = ended(lab, run.id)
    assert done.status == "completed" and done.done == done.total == 11
    assert Path(done.path).exists()
    (started,) = bodies(heard, MeasurementStarted)
    assert started.run.id == run.id and "I-V" in {p.title for p in started.plots}
    rows = [row for batch in bodies(heard, MeasurementRecords) for row in batch.rows]
    assert len(rows) == 11 and rows[-1]["voltage"] == pytest.approx(2e-3, abs=1e-4)
    assert bodies(heard, MeasurementProgress)[-1].done == 11
    kinds = [type(event.body) for event in heard]
    last_record = max(i for i, kind in enumerate(kinds) if kind is MeasurementRecords)
    assert kinds.index(MeasurementFinished) > last_record  # after every record
    assert bodies(heard, MeasurementFinished)[0].run.status == "completed"
    assert lab.call(ListRuns())[-1].id == run.id


def test_measurements_run_side_by_side_and_stop(lab):
    monitor = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=MONITOR))
    iv = lab.call(
        StartMeasurement(
            procedure=IV_CURVE, parameters=FAST_IV, devices={"bias": "sis_bias_1"}
        )
    )
    assert monitor.id != iv.id
    assert ended(lab, iv.id).status == "completed"
    assert lab.call(WaitMeasurement(id=monitor.id, timeout=0)).status == "running"
    lab.call(CancelMeasurement(id=monitor.id))
    assert ended(lab, monitor.id).status == "cancelled"


@pytest.mark.parametrize(
    "start, code",
    [
        (StartMeasurement(procedure="sis.nothing"), ErrorCode.NOT_FOUND),
        (
            StartMeasurement(
                procedure=IV_CURVE,
                parameters={"voltage": {"start": 0, "stop": 1, "points": 0}},
            ),
            ErrorCode.INVALID_ARGUMENTS,
        ),
        (
            StartMeasurement(procedure=IV_CURVE, devices={"bias": "sis_bias_9"}),
            ErrorCode.INVALID_ARGUMENTS,
        ),
        (WaitMeasurement(id=999), ErrorCode.NOT_FOUND),
        (WaitMeasurement(id=1, timeout=61), ErrorCode.INVALID_ARGUMENTS),
    ],
)
def test_what_cannot_run_is_refused(lab, start, code):
    with pytest.raises(LabError) as caught:
        lab.call(start)
    assert caught.value.code == code


def test_what_a_sweep_sets_is_told_a_few_times_a_second(lab):
    from thzdaq_api.events import GetSnapshot, QuantitySet

    heard = []
    lab.subscribe(heard.append)
    sweep = {
        "voltage": {"start": 0.0, "stop": 2e-3, "points": 41},
        "settle_time": 0.01,
        "first_point_delay": 0.0,
    }
    run = lab.call(
        StartMeasurement(
            procedure=IV_CURVE, parameters=sweep, devices={"bias": "sis_bias_1"}
        )
    )
    ended(lab, run.id)
    told = [e for e in heard if isinstance(e.body, QuantitySet)]
    sets = [e.body for e in told if e.body.origin == f"#{run.id}"]
    # 41 points in about half a second: a few events along the sweep
    assert 3 <= len(sets) <= 10
    assert any(0 < s.value <= 2e-3 for s in sets)
    # on_exit puts the bias back: the last value told, known in the snapshot
    assert sets[-1].value == 0.0
    assert lab.call(GetSnapshot()).values["sis_bias_1"]["voltage_set"] == 0.0


def test_a_measurement_goes_to_the_workspace_its_client_names(lab, tmp_path):
    first, second = tmp_path / "A", tmp_path / "B"
    first.mkdir()
    second.mkdir()

    def run(workspace=None):
        started = lab.call(
            StartMeasurement(
                procedure=IV_CURVE,
                parameters=FAST_IV,
                devices={"bias": "sis_bias_1"},
                workspace=workspace and str(workspace),
            )
        )
        return ended(lab, started.id)

    runs = [run(first), run(second), run()]
    for info, folder in zip(runs, (first, second, tmp_path)):
        assert info.workspace == str(folder.resolve())
        assert Path(info.path).parent.parent == folder.resolve() / "data"
    # One number names one measurement of the daemon, in whichever folder
    assert [info.id for info in runs] == sorted({info.id for info in runs})
    with pytest.raises(LabError) as caught:
        run(tmp_path / "nowhere")
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
