"""A script's own measurement: a session the daemon keeps and ends, restoring
what the script asked (contract: LocalLab and RemoteLab)."""

import math

import pytest
from lab_helpers import Window, bodies, calling, wait_for
from thzdaq_api.devices import ReadDevice, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import MeasurementLog, MeasurementPlotted, MeasurementRecords
from thzdaq_api.leases import EXCLUSIVE, READ, SHARED, ListLeases
from thzdaq_api.measurement_file import Column, read_measurement
from thzdaq_api.measurements import (
    CancelMeasurement,
    GetRunSnapshot,
    PlotInfo,
    WaitMeasurement,
)
from thzdaq_api.origins import CLI, GUI, script
from thzdaq_api.sessions import (
    AdvanceSession,
    CallOnExit,
    EndSession,
    KeepSession,
    LogSession,
    ParseSweep,
    PlotSession,
    RecordSession,
    RestoreOnExit,
    ScriptSource,
    StartSession,
)

SCRIPT = script("scan")  # a person's script
AGENTS = script("scan", by_agent=True)  # an agent's


def bias(value, session=None):
    return SetQuantity(
        ref="sis_bias_1", key="voltage_set", value=value, session=session
    )


def bias_now(lab):
    return lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",))).values[
        "voltage_set"
    ]


def plot(table, x, y):
    return PlotInfo(key="", title="", table=table, x=x, y=y)


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def test_a_session_is_a_measurement_the_script_fills(lab, tmp_path):
    source = ScriptSource("scripts/scan.py", "ab12", "print('scan')")
    run = lab.call(
        StartSession(
            title="scan",
            devices=("sis_bias_1", "power_meter_1"),
            exclusive=("sis_bias_1",),
            parameters={"bias": "2:3:3 mV"},
            comment="narrow",
            workspace=str(tmp_path),
            script=source,
            total=2,
        )
    )
    assert (run.procedure, run.title, run.status) == ("script:scan", "scan", "running")
    assert run.devices == {"sis_bias_1": "sis_bias_1", "power_meter_1": "power_meter_1"}
    leases = {(lease.device, lease.mode) for lease in lab.call(ListLeases())}
    assert leases == {("sis_bias_1", EXCLUSIVE), ("power_meter_1", SHARED)}

    power = Column("power", "IF power", "dBm", "power_meter_1/power")
    for v in (2e-3, 3e-3):
        state = lab.call(
            RecordSession(
                id=run.id,
                table="pv",
                rows=({"voltage_set": v, "power": -30.0, "load": "hot"},),
                columns=(power,),
            )
        )
        assert state.status == "running" and not state.cancelled
        lab.call(AdvanceSession(id=run.id))
    drawn = lab.call(PlotSession(id=run.id, plot=plot("pv", "voltage_set", "power")))
    assert (drawn.x_label, drawn.y_label) == ("Voltage setpoint, V", "IF power, dBm")
    assert drawn.title and drawn.key
    lab.call(LogSession(id=run.id, message="halfway"))
    assert lab.call(GetRunSnapshot(id=run.id)).plots == (drawn,)

    ended = lab.call(EndSession(id=run.id))
    assert ended.status == "completed" and ended.done == 2
    saved = read_measurement(ended.path)
    assert saved.procedure == "script:scan" and saved.comment == "narrow"
    assert saved.parameters == {"bias": "2:3:3 mV"}
    assert set(saved.devices) == {"sis_bias_1", "power_meter_1"}
    assert saved.column("pv", "voltage_set") == [2e-3, 3e-3]
    assert saved.tables["pv"].get_column("power") == power
    assert saved.metadata["script"] == {
        "path": "scripts/scan.py",
        "sha256": "ab12",
        "text": "print('scan')",
    }
    assert saved.plots[-1]["y"] == "power"
    assert not lab.call(ListLeases())


def test_its_plots_and_records_are_told_at_once(lab, lab_as):
    window = Window(lab_as(GUI))
    try:
        run = lab.call(StartSession(title="scan"))
        drawn = lab.call(PlotSession(id=run.id, plot=plot("pv", "voltage", "power")))
        wait_for(lambda: bodies(window.heard, MeasurementPlotted))
        (told,) = bodies(window.heard, MeasurementPlotted)
        assert (told.id, told.plot) == (run.id, drawn)
        rows = ({"voltage": 1e-3, "power": -30.0}, {"voltage": 2e-3, "power": -31.0})
        lab.call(RecordSession(id=run.id, table="pv", rows=rows))
        wait_for(lambda: bodies(window.heard, MeasurementRecords))
        assert [r.rows for r in bodies(window.heard, MeasurementRecords)] == [rows]
        lab.call(EndSession(id=run.id))
    finally:
        window.stop()


def test_the_daemon_restores_at_the_end(lab):
    lab.call(bias("1mV"))
    run = lab.call(StartSession(title="scan", exclusive=("sis_bias_1",)))
    kept = lab.call(RestoreOnExit(id=run.id, ref="sis_bias_1", key="voltage_set"))
    assert kept.value == pytest.approx(1e-3)
    lab.call(CallOnExit(id=run.id, ref="chopper_1", action="to_cold"))
    lab.call(bias("3mV", session=run.id))  # its own sweep: no conflict
    assert bias_now(lab) == pytest.approx(3e-3)
    lab.call(EndSession(id=run.id))
    assert bias_now(lab) == pytest.approx(1e-3)
    saved = read_measurement(lab.call(WaitMeasurement(id=run.id, timeout=0)).path)
    assert "chopper_1" in saved.devices  # joined by its action at the end


def test_its_sweep_is_its_own_and_others_ask_to_share(lab, lab_as):
    run = lab.call(StartSession(title="scan", exclusive=("sis_bias_1",)))
    lab.call(bias("2mV", session=run.id))
    with pytest.raises(LabError) as caught:
        lab_as(CLI).call(bias("1mV"))
    assert caught.value.code == ErrorCode.CONFLICT
    lab_as(CLI).call(
        SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV", share=True)
    )
    lab.call(EndSession(id=run.id))
    saved = read_measurement(lab.call(WaitMeasurement(id=run.id, timeout=0)).path)
    assert saved.metadata["conflicts"][0]["by"] == CLI


def test_a_device_it_did_not_name_joins_it(lab, lab_as):
    window = Window(lab_as(GUI))
    try:
        run = lab.call(StartSession(title="scan"))
        lab.call(ReadDevice(ref="power_meter_1", session=run.id))
        lab.call(bias("1mV", session=run.id))
        leases = {(lease.device, lease.mode) for lease in lab.call(ListLeases())}
        assert leases == {("power_meter_1", READ), ("sis_bias_1", SHARED)}
        wait_for(lambda: len(bodies(window.heard, MeasurementLog)) == 2)
        assert all(
            "devices=" in log.message for log in bodies(window.heard, MeasurementLog)
        )
        ended = lab.call(EndSession(id=run.id))
        assert set(ended.devices) == {"power_meter_1", "sis_bias_1"}
    finally:
        window.stop()


def test_a_cancel_reaches_the_script_which_ends_the_session(lab, lab_as):
    lab.call(bias("1mV"))
    run = lab.call(StartSession(title="scan", devices=("sis_bias_1",)))
    lab.call(RestoreOnExit(id=run.id, ref="sis_bias_1", key="voltage_set"))
    lab.call(bias("2mV", session=run.id))
    thread, done = calling(lab, KeepSession(id=run.id, wait=5.0))
    lab_as(CLI).call(CancelMeasurement(id=run.id))
    thread.join(5)
    assert done["result"].cancelled and done["result"].status == "running"
    ended = lab.call(EndSession(id=run.id, status="cancelled"))
    assert ended.status == "cancelled"
    assert bias_now(lab) == pytest.approx(1e-3)


def test_a_cancelled_script_that_goes_on_is_stopped(lab, lab_as, monkeypatch):
    from thzdaq_core.application import scripts

    monkeypatch.setattr(scripts, "CANCEL_S", 0.2)
    run = lab.call(StartSession(title="scan"))
    lab_as(CLI).call(CancelMeasurement(id=run.id))
    assert lab.call(WaitMeasurement(id=run.id, timeout=5)).status == "cancelled"
    with pytest.raises(LabError) as caught:
        lab.call(RecordSession(id=run.id, table="t", rows=({"x": 1},)))
    assert caught.value.code == ErrorCode.NOT_ALLOWED
    assert lab.call(KeepSession(id=run.id)).status == "cancelled"


def test_a_silent_script_ends_interrupted_and_is_restored(lab):
    lab.call(bias("1mV"))
    run = lab.call(StartSession(title="scan", devices=("sis_bias_1",), silent=0.3))
    lab.call(RestoreOnExit(id=run.id, ref="sis_bias_1", key="voltage_set"))
    lab.call(bias("2mV", session=run.id))
    ended = lab.call(WaitMeasurement(id=run.id, timeout=5))
    assert ended.status == "interrupted" and "silent" in ended.error
    assert bias_now(lab) == pytest.approx(1e-3)
    assert not lab.call(ListLeases())


def test_a_script_fails_with_its_own_words(lab):
    run = lab.call(StartSession(title="scan"))
    ended = lab.call(
        EndSession(
            id=run.id,
            status="failed",
            error="ZeroDivisionError: division by zero",
            traceback="Traceback: scan.py, line 3",
        )
    )
    assert ended.status == "failed" and ended.error.startswith("ZeroDivisionError")
    saved = read_measurement(ended.path)
    assert saved.metadata["traceback"] == "Traceback: scan.py, line 3"
    with pytest.raises(LabError) as caught:
        lab.call(EndSession(id=run.id, status="finished"))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS


def test_only_its_script_records_into_a_session(lab, lab_as):
    run = lab.call(StartSession(title="scan", devices=("sis_bias_1",)))
    other = lab_as(CLI)
    for operation in (
        RecordSession(id=run.id, table="t", rows=({"x": 1},)),
        bias("1mV", session=run.id),
    ):
        with pytest.raises(LabError) as caught:
            other.call(operation)
        assert caught.value.code == ErrorCode.DENIED
    other.call(CancelMeasurement(id=run.id))  # anyone may stop it
    lab.call(EndSession(id=run.id, status="cancelled"))


def test_values_travel_with_complex_and_nan(lab):
    run = lab.call(StartSession(title="scan"))
    from thzdaq_api.data import encode_values

    row = {"s11": complex(0.5, -0.5), "tn": math.nan}
    lab.call(RecordSession(id=run.id, table="s", rows=(encode_values(row),)))
    saved = read_measurement(lab.call(EndSession(id=run.id)).path)
    assert saved.column("s", "s11") == [complex(0.5, -0.5)]
    assert math.isnan(saved.column("s", "tn")[0])


def test_a_sweep_is_typed_as_people_type_it(lab):
    sweep = lab.call(ParseSweep(text="2:3:51", unit="mV"))
    assert sweep.unit == "V" and len(sweep.values) == 51
    assert sweep.values[0] == pytest.approx(2e-3)
    assert sweep.values[-1] == pytest.approx(3e-3)
    assert lab.call(ParseSweep(text="0:90:10", unit="deg")).unit == "deg"
    with pytest.raises(LabError) as caught:
        lab.call(ParseSweep(text="2:3", unit="mV"))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS


# What a script may do: an agent's asks a person for its session once
def test_an_agents_session_is_allowed_by_a_person_once(lab_as, window):
    scan = lab_as(AGENTS, "script")
    thread, done = calling(
        scan, StartSession(title="scan", devices=("sis_bias_1",), comment="narrow")
    )
    approval = window.asked()
    assert approval.title == "Start script scan" and approval.origin == AGENTS
    assert "sis_bias_1 shared" in approval.text and "narrow" in approval.text
    window.answer(allowed=True)
    thread.join(5)
    run = done["result"]
    asked = len(window.waiting())
    scan.call(bias("1mV", session=run.id))  # its own device: nobody asked
    scan.call(RestoreOnExit(id=run.id, ref="sis_bias_1", key="voltage_set"))
    scan.call(RecordSession(id=run.id, table="t", rows=({"x": 1},)))
    scan.call(AdvanceSession(id=run.id))
    assert len(window.waiting()) == asked
    scan.call(EndSession(id=run.id))


def test_an_agents_script_asks_for_a_device_it_did_not_name_once(lab, lab_as, window):
    scan = lab_as(AGENTS, "script")
    thread, done = calling(scan, StartSession(title="scan"))
    window.answer(allowed=True)
    thread.join(5)
    run = done["result"]
    thread, done = calling(scan, bias("1mV", session=run.id))
    assert window.asked().title.startswith("sis_bias_1")
    window.answer(allowed=True)
    thread.join(5)
    scan.call(bias("2mV", session=run.id))  # it joined: not asked again
    assert bias_now(lab) == pytest.approx(2e-3)
    scan.call(EndSession(id=run.id))


def test_a_persons_script_changes_the_bench_as_the_person_would(lab, lab_as, window):
    scan = lab_as(SCRIPT, "script")
    run = scan.call(StartSession(title="scan", devices=("sis_bias_1",)))
    scan.call(bias("1mV", session=run.id))
    scan.call(
        SetQuantity(ref="sis_bias_2", key="voltage_set", value="1mV", session=run.id)
    )  # not named: it joins
    scan.call(bias("2mV"))  # outside its session too
    assert not window.waiting() and bias_now(lab) == pytest.approx(2e-3)
    scan.call(EndSession(id=run.id))


def test_a_dangerous_step_of_a_session_is_still_asked(lab_as, window):
    scan = lab_as(SCRIPT, "script")
    run = scan.call(StartSession(title="scan", devices=("sis_bias_1",)))
    thread, done = calling(
        scan,
        SetQuantity(ref="sis_bias_1", key="active", value=False, session=run.id),
    )
    assert window.asked().confirm == "sis_bias_1"
    window.answer(allowed=False)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    scan.call(EndSession(id=run.id))


def test_a_scripts_conflict_is_the_persons_to_allow(lab, lab_as, window):
    sweep = lab.call(StartSession(title="sweep", exclusive=("sis_bias_1",)))
    scan = lab_as(SCRIPT, "script")
    thread, done = calling(scan, StartSession(title="scan", devices=("sis_bias_1",)))
    approval = window.asked()
    assert f"#{sweep.id}" in approval.warning
    window.answer(allowed=True)
    thread.join(5)
    run = done["result"]
    assert run.conflicts and run.conflicts[0]["run"] == sweep.id
    scan.call(bias("1mV", session=run.id))  # shared: not asked again
    scan.call(EndSession(id=run.id))
    lab.call(EndSession(id=sweep.id))
