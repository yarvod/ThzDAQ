"""The bench as a script uses it (thzdaq_api.lab, thzdaq_api.script): functions,
device objects, runs and the script's own measurements (contract: LocalLab and
RemoteLab)."""

import threading
import time

import pytest
from lab_helpers import Window, wait_for
from thzdaq_api.data import Measured
from thzdaq_api.devices import ReadDevice
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Bench
from thzdaq_api.leases import READ, ListLeases
from thzdaq_api.measurement_file import Column, read_measurement
from thzdaq_api.measurements import CancelMeasurement
from thzdaq_api.origins import ANSWERING_CLI, CLI, GUI, script
from thzdaq_api.procedures import IV_CURVE
from thzdaq_api.script import AnsweredHere, Cancelled
from thzdaq_api.sessions import ScriptSource

SCRIPT = script("scan")
SOURCE = ScriptSource("scripts/scan.py", "ab12", "...")


@pytest.fixture
def bench(lab, tmp_path):
    return Bench(lab, tmp_path, SOURCE)


def bias_now(lab):
    return lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",))).values[
        "voltage_set"
    ]


def test_devices_are_objects_of_their_quantities_and_actions(bench):
    bias = bench["sis_bias_1"]
    bias.voltage_set = "2mV"
    setpoint = bias.voltage_set
    assert isinstance(setpoint, Measured) and setpoint == pytest.approx(2e-3)
    assert (setpoint.unit, setpoint.source) == ("V", "sis_bias_1/voltage_set")
    assert setpoint * 1000 == pytest.approx(2.0)  # a float in calculations
    reading = bias.read()
    assert reading.voltage == reading["voltage"] and reading.current.unit == "A"
    assert bias.read("voltage_set", display=True).voltage_set == "2 mV"
    bias["voltage_set"] = 1e-3
    assert bench.read("sis_bias_1", "voltage_set")["voltage_set"] == pytest.approx(1e-3)
    bench["chopper_1"].to_hot()
    assert "voltage_set" in dir(bias) and "to_cold" in dir(bench["chopper_1"])
    with pytest.raises(AttributeError):
        bias.voltag_set
    with pytest.raises(LabError) as caught:
        bias.voltag_set = 1e-3
    assert caught.value.code == ErrorCode.NOT_FOUND


def test_a_procedure_runs_and_its_table_is_read(bench):
    run = bench.run(
        IV_CURVE,
        bias=bench["sis_bias_1"],
        voltage="0:2:11",
        settle_time=0.0,
        first_point_delay=0.0,
    )
    assert run.id in {info.id for info in bench.measurements()}
    assert run.wait(progress=False).status == "completed"
    iv = run.table("iv")
    assert len(iv["voltage"]) == 11 and iv.get_column("current").unit == "A"
    with pytest.raises(LabError) as caught:
        run.table("pv")
    assert caught.value.code == ErrorCode.NOT_FOUND
    assert not bench.status()


def test_a_slot_two_devices_suit_is_asked_for(bench):
    with pytest.raises(LabError) as caught:
        bench.start(IV_CURVE, voltage="0:2:11")
    assert "sis_bias_1" in caught.value.message and "sis_bias_2" in caught.value.message


def test_a_scripts_measurement_records_what_values_know(bench, lab):
    bias, pm = bench["sis_bias_1"], bench["power_meter_1"]
    bias.voltage_set = "1mV"
    with bench.measurement(
        "pv", devices=[bias, pm], exclusive=[bias], columns={"y": ("Y-factor", "dB")}
    ) as m:
        assert bench.session is m
        m.plot("scan", x="voltage_set", y="power")
        assert m.restore(bias, "voltage_set") == pytest.approx(1e-3)
        for v in m.sweep("2:3:3", unit="mV"):
            bias.voltage_set = v
            m.record("scan", voltage_set=v, power=pm.power, y=1.5, load="hot")
            m.progress()
        assert bias_now(lab) == pytest.approx(3e-3)
    assert bench.session is None
    assert m.run.status == "completed" and m.run.done == 3
    assert bias_now(lab) == pytest.approx(1e-3)  # restored by the daemon
    saved = read_measurement(m.run.path)
    columns = {c.key: c for c in saved.tables["scan"].columns}
    assert columns["voltage_set"] == Column("voltage_set", "Voltage setpoint", "V")
    assert columns["power"].source == "power_meter_1/power"
    assert columns["power"].unit == "dBm"
    assert columns["y"] == Column("y", "Y-factor", "dB")
    assert saved.column("scan", "voltage_set") == pytest.approx([2e-3, 2.5e-3, 3e-3])
    assert saved.metadata["script"]["path"] == "scripts/scan.py"
    assert saved.metadata["plots"][0]["table"] == "scan"


def test_a_device_the_script_did_not_name_joins_its_measurement(bench, lab):
    with bench.measurement("monitor") as m:
        bench["power_meter_1"].power
        leases = lab.call(ListLeases())
        assert [(lease.device, lease.mode, lease.run) for lease in leases] == [
            ("power_meter_1", READ, m.id)
        ]
    assert "power_meter_1" in m.run.devices


def test_a_cancel_from_elsewhere_ends_it_and_the_script_goes_on(bench, lab, lab_as):
    bias = bench["sis_bias_1"]
    bias.voltage_set = "1mV"
    began = time.monotonic()
    with bench.measurement("pv", devices=[bias]) as m:
        m.restore(bias, "voltage_set")
        for step, v in enumerate(m.sweep([2e-3, 3e-3, 4e-3])):
            bias.voltage_set = v
            if step == 1:
                lab_as(CLI).call(CancelMeasurement(id=m.id))
                m.sleep(10)  # wakes at once
    assert time.monotonic() - began < 5
    assert m.cancelled and m.run.status == "cancelled"
    assert bias_now(lab) == pytest.approx(1e-3)
    assert read_measurement(m.run.path).status == "cancelled"


def test_a_failing_script_ends_its_measurement_failed(bench):
    with pytest.raises(ZeroDivisionError):
        with bench.measurement("pv") as m:
            m.record("t", x=1.0)
            1 / 0
    assert m.run.status == "failed" and m.run.error.startswith("ZeroDivisionError")
    assert "1 / 0" in read_measurement(m.run.path).metadata["traceback"]


def test_the_script_is_kept_alive_while_it_works(bench):
    with bench.measurement("slow", silent=0.3) as m:
        time.sleep(0.8)  # the script's own work, longer than silent
        m.record("t", x=1.0)
    assert m.run.status == "completed"


def test_a_person_at_the_scripts_terminal_allows_its_start(lab_as, tmp_path):
    asked = []

    def typed(prompt, gone):
        asked.append(prompt)
        return "y"

    approve = AnsweredHere(lab_as(CLI, ANSWERING_CLI), SCRIPT, typed)
    bench = Bench(lab_as(SCRIPT, "script"), tmp_path, approve=approve)
    with bench.measurement("scan", devices=["sis_bias_1"]) as m:
        bench["sis_bias_1"].voltage_set = "1mV"  # its own device: not asked
        m.record("t", x=1.0)
    assert asked == ["allow? [y/N] "] and m.run.status == "completed"
    refusing = AnsweredHere(lab_as(CLI, ANSWERING_CLI), SCRIPT, lambda p, g: "n")
    with pytest.raises(LabError) as caught:
        Bench(lab_as(SCRIPT, "script"), tmp_path, approve=refusing).measurement(
            "scan"
        ).__enter__()
    assert caught.value.code == ErrorCode.DENIED


def test_a_window_may_answer_first(lab_as, tmp_path):
    window = Window(lab_as(GUI))
    try:
        waited = threading.Event()

        def typed(prompt, gone):
            waited.set()
            gone.wait(5)  # the person here types nothing
            return None

        approve = AnsweredHere(lab_as(CLI, ANSWERING_CLI), SCRIPT, typed)
        bench = Bench(lab_as(SCRIPT, "script"), tmp_path, approve=approve)
        answer = threading.Thread(
            target=lambda: (wait_for(waited.is_set), window.answer(allowed=True))
        )
        answer.start()
        with bench.measurement("scan") as m:
            pass
        answer.join(5)
        assert m.run.status == "completed"
    finally:
        window.stop()


def test_cancelled_is_the_scripts_to_catch_too(bench, lab_as):
    with bench.measurement("pv") as m:
        lab_as(CLI).call(CancelMeasurement(id=m.id))
        wait_for(lambda: m.cancelled)
        with pytest.raises(Cancelled):
            m.check_cancel()
    assert m.run.status == "cancelled"
