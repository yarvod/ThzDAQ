"""Procedures and measurements through LocalLab."""

from pathlib import Path

import pytest
from thzdaq_api import present
from lab_helpers import bodies, wait_for
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.events import (
    MeasurementFinished,
    MeasurementProgress,
    MeasurementRecords,
    MeasurementStarted,
)
from thzdaq_api.measurements import (
    CancelMeasurement,
    DescribeProcedure,
    GetRunSnapshot,
    ListProcedures,
    ListRuns,
    StartMeasurement,
    SummarizeMeasurement,
    WaitMeasurement,
)
from thzdaq_api.procedures import (
    CURRENT_VS_VOLTAGE,
    MONITOR_VALUES_VS_TIME,
    NOISE_TEMPERATURE_VS_VOLTAGE,
)

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
    assert {CURRENT_VS_VOLTAGE, MONITOR_VALUES_VS_TIME} <= {
        p.name for p in lab.call(ListProcedures())
    }
    info = lab.call(DescribeProcedure(procedure=CURRENT_VS_VOLTAGE))
    voltage = next(p for p in info.parameters if p.name == "voltage")
    assert (voltage.kind, voltage.unit, voltage.display_unit) == ("sweep", "V", "mV")
    assert voltage.default == {"start": 0.0, "stop": 7e-3, "points": 351}
    assert [(s.name, s.kind) for s in info.slots] == [("bias", "sis_bias")]
    assert "VoltageSource" in info.slots[0].capabilities
    assert "I-V" in {p.title for p in info.plots}
    assert info.guide.startswith("The first look at a junction")


def test_every_built_in_procedure_tells_how_to_measure_with_it(lab):
    """Agents and the assistant read it in describe_procedure."""
    for summary in lab.call(ListProcedures()):
        info = lab.call(DescribeProcedure(procedure=summary.name))
        assert len(info.guide) > 100, summary.name


def test_slots_follow_the_parameters(lab):
    plain = lab.call(
        DescribeProcedure(
            procedure=NOISE_TEMPERATURE_VS_VOLTAGE, parameters={"hot_cold": False}
        )
    )
    hot_cold = lab.call(DescribeProcedure(procedure=NOISE_TEMPERATURE_VS_VOLTAGE))
    assert "load" not in {s.name for s in plain.slots}
    assert "load" in {s.name for s in hot_cold.slots}
    # The Y-factor is drawn only when there is a hot and a cold load
    assert len(hot_cold.plots) > len(plain.plots)


def test_a_run_is_described_with_its_steps_and_plot_window(lab):
    iv = lab.call(DescribeProcedure(procedure=CURRENT_VS_VOLTAGE, parameters=FAST_IV))
    assert iv.steps == 11 and iv.plot_window is None
    voltage = next(p for p in iv.parameters if p.name == "voltage")
    assert voltage.max_points and voltage.max_points > 11
    monitor = lab.call(
        DescribeProcedure(
            procedure=MONITOR_VALUES_VS_TIME,
            parameters={**MONITOR, "watch": ["power_meter_1", "sis_bias_1/voltage"]},
            devices={"power_meter_1": "power_meter_1", "sis_bias_1": "sis_bias_1"},
        )
    )
    assert monitor.steps is None and monitor.plot_window == 600.0
    assert [s.capabilities for s in monitor.slots] == [(), ()]  # any device
    # The graphs of the units its devices read, not every one it may fill
    assert {p.title for p in monitor.plots} == {"P-t", "V-t"}


def test_every_invalid_parameter_is_named(lab):
    with pytest.raises(LabError) as error:
        lab.call(
            DescribeProcedure(
                procedure=CURRENT_VS_VOLTAGE,
                parameters={**FAST_IV, "settle_time": -1, "first_point_delay": "x"},
            )
        )
    assert error.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "Settle time" in str(error.value) and "First point" in str(error.value)


def test_a_measurement_runs_and_is_heard(lab):
    heard = []
    lab.subscribe(heard.append)
    run = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
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
    monitor = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=MONITOR)
    )
    iv = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters=FAST_IV,
            devices={"bias": "sis_bias_1"},
        )
    )
    assert monitor.id != iv.id
    assert ended(lab, iv.id).status == "completed"
    assert lab.call(WaitMeasurement(id=monitor.id, timeout=0)).status == "running"
    lab.call(CancelMeasurement(id=monitor.id))
    assert ended(lab, monitor.id).status == "cancelled"


def test_run_snapshot_and_later_events_contain_each_row_once(lab):
    from thzdaq_api.measurement_file import read_measurement

    run = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=MONITOR)
    )
    initial = []
    stop_initial = lab.subscribe(initial.append)
    wait_for(lambda: len(bodies(initial, MeasurementProgress)) >= 3)
    snapshot = lab.call(GetRunSnapshot(id=run.id))
    stop_initial()
    assert snapshot.run.id == run.id
    assert {plot.title for plot in snapshot.plots} == {"P-t"}
    assert snapshot.rows["samples"]
    heard = []
    unsubscribe = lab.subscribe(heard.append, since=snapshot.seq)
    wait_for(lambda: len(bodies(heard, MeasurementRecords)) >= 2)
    lab.call(CancelMeasurement(id=run.id))
    done = ended(lab, run.id)
    final = lab.call(GetRunSnapshot(id=run.id))
    unsubscribe()
    rows = list(snapshot.rows.get("samples", ()))
    rows.extend(
        row for batch in bodies(heard, MeasurementRecords) for row in batch.rows
    )
    assert rows == list(final.rows["samples"])
    assert len(rows) == read_measurement(done.path).size
    assert final.run.status == "cancelled"
    assert final.seq >= snapshot.seq
    with pytest.raises(LabError) as caught:
        lab.call(GetRunSnapshot(id=99999))
    assert caught.value.code == ErrorCode.NOT_FOUND


def test_a_summary_tells_the_records_and_ranges_without_arrays(lab):
    run = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters=FAST_IV,
            devices={"bias": "sis_bias_1"},
        )
    )
    assert ended(lab, run.id).status == "completed"
    summary = lab.call(SummarizeMeasurement(id=run.id))
    assert summary.run.id == run.id and summary.run.status == "completed"
    (iv,) = summary.tables
    assert iv.records == 11
    voltage = next(c for c in iv.columns if c.key == "voltage_set")
    assert (voltage.unit, voltage.minimum, voltage.maximum) == ("V", 0.0, 2e-3)
    assert "m" in {p.name for p in voltage.prefixes}
    # what it was run with, as its file keeps it: agents read it too
    assert summary.parameters == read_measurement(summary.run.path).parameters
    assert summary.parameters["settle_time"] == FAST_IV["settle_time"]
    told = present.summary(summary)
    assert "parameters (SI): " in told and "settle_time = " in told
    with pytest.raises(LabError) as caught:
        lab.call(SummarizeMeasurement(id=99999))
    assert caught.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    "start, code",
    [
        (StartMeasurement(procedure="sis.nothing"), ErrorCode.NOT_FOUND),
        (
            StartMeasurement(
                procedure=CURRENT_VS_VOLTAGE,
                parameters={"voltage": {"start": 0, "stop": 1, "points": 0}},
            ),
            ErrorCode.INVALID_ARGUMENTS,
        ),
        (
            StartMeasurement(
                procedure=CURRENT_VS_VOLTAGE, devices={"bias": "sis_bias_9"}
            ),
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
            procedure=CURRENT_VS_VOLTAGE,
            parameters=sweep,
            devices={"bias": "sis_bias_1"},
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
                procedure=CURRENT_VS_VOLTAGE,
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


def test_a_comment_goes_into_the_file_of_a_measurement(lab, tmp_path):
    from thzdaq_api.measurement_file import read_measurement
    from thzdaq_api.measurements import SetComment

    done = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters=FAST_IV,
            devices={"bias": "sis_bias_1"},
        )
    )
    done = ended(lab, done.id)
    lab.call(SetComment(path=done.path, comment="after the warm-up"))
    assert read_measurement(done.path).comment == "after the warm-up"
    # A running one keeps it and saves it with its data
    running = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=MONITOR)
    )
    lab.call(SetComment(path=running.path, comment="overnight"))
    lab.call(CancelMeasurement(id=running.id))
    assert read_measurement(ended(lab, running.id).path).comment == "overnight"
    with pytest.raises(LabError) as caught:
        lab.call(SetComment(path=str(tmp_path / "nothing.json"), comment="x"))
    assert caught.value.code == ErrorCode.NOT_FOUND


def test_parameters_are_typed_as_people_type_them(lab):
    typed = {"voltage": "0:2:11", "settle_time": "0", "first_point_delay": "0"}
    info = lab.call(DescribeProcedure(procedure=CURRENT_VS_VOLTAGE, typed=typed))
    assert info.steps == 11
    with pytest.raises(LabError) as error:
        lab.call(
            DescribeProcedure(procedure=CURRENT_VS_VOLTAGE, typed={"voltage": "0:2"})
        )
    assert error.value.code == ErrorCode.INVALID_ARGUMENTS
    assert "start:stop:points" in str(error.value)
    planned = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            typed=typed,
            devices={"bias": "sis_bias_1"},
            dry_run=True,
        )
    )
    assert planned.total == 11
