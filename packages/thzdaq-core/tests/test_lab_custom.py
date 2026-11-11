"""The bench's own measurements (Custom): scripts of its library described into
procedures custom.<name> and run as their scripts' processes (contract:
LocalLab and RemoteLab). The scripts here use no bench; those that measure
run on a daemon of their own (thzdaq-daemon's test_custom.py)."""

import copy
import json
from pathlib import Path

import pytest
from lab_helpers import Window, bodies, calling, wait_for
from thzdaq_api.custom import (
    CheckCustom,
    ListCustom,
    ParseValue,
    ReadCustom,
    ValueDeclared,
    WriteCustom,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ProceduresChanged, ScriptOutput
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import (
    CancelMeasurement,
    DescribeProcedure,
    ListProcedures,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.origins import GUI
from thzdaq_api.scripts import ListScripts
from thzdaq_api.station import GetStation, UpdateStation

PV = '''"""P-V hot/cold

IF power against bias on both loads.
"""
from thzdaq import connect, device, plot, value

bias = device("SIS bias", kind="sis_bias")
detector = device("Detector", "PowerDetector")
voltage = value("Bias voltage", "0:7:351", unit="mV")
t_hot, t_cold = value("Hot load", 300, unit="K"), value("Cold load", 77, unit="K")
pv = plot("P-V", table="pv", x="voltage", y="power", group_by="load")

lab = connect()
raise SystemExit("never here when described")
'''
# A script told its inputs: they are only printed, the bench is not used
TOLD = '''"""Told"""
import os
from thzdaq import value

voltage = value("Bias voltage", "0:7:351", unit="mV")
settle = value("Settle", 10, unit="ms")
loads = value("Loads", ["hot", "cold"])
print(repr(voltage), float(settle), settle.unit, loads)
print(os.environ["THZDAQ_INPUTS"])
'''


def library(lab) -> Path:
    folder = lab.assembled.customs.library.folder
    folder.mkdir(exist_ok=True)
    return folder


def saved(lab, name: str, text: str) -> Path:
    path = library(lab) / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    return path


def summary(lab, name: str):
    return next(p for p in lab.call(ListProcedures()) if p.name == f"custom.{name}")


def test_a_script_of_the_library_is_a_procedure_with_its_form(lab):
    saved(lab, "pv", PV)
    found = summary(lab, "pv")
    assert (found.title, found.description, found.error) == (
        "P-V hot/cold", "IF power against bias on both loads.", "",
    )  # fmt: skip
    assert [p.key for p in found.plots] == ["custom.pv.pv"]
    info = lab.call(DescribeProcedure(procedure="custom.pv"))
    voltage, t_hot, t_cold = info.parameters
    assert (voltage.name, voltage.kind, voltage.unit, voltage.display_unit) == (
        "voltage", "sweep", "V", "mV",
    )  # fmt: skip
    assert voltage.default == {"start": 0.0, "stop": 0.007, "points": 351}
    assert (t_hot.name, t_hot.default, t_cold.default) == ("t_hot", 300.0, 77.0)
    bias, detector = info.slots
    assert (bias.name, bias.title, bias.kind) == ("bias", "SIS bias", "sis_bias")
    assert detector.capabilities == ("PowerDetector",)
    (plot,) = info.plots
    assert (plot.title, plot.group_by, plot.y_label) == ("P-V", ("load",), "Power, dBm")
    typed = lab.call(
        DescribeProcedure(procedure="custom.pv", typed={"voltage": "1:2:11"})
    )
    assert typed.parameters[0].name == "voltage"


@pytest.mark.parametrize(
    "text, told",
    [
        ("from thzdaq import value\nx = value('X', 1\n", "line 2"),
        (
            "from thzdaq import connect, value\nlab = connect()\nx = value('X', 1)\n",
            "after connect()",
        ),
        ("from thzdaq import value\nprint(value('X', 1))\n", "assign value(...)"),
        (
            "import nothing_of_the_kind\nfrom thzdaq import value\nx = value('X', 1)\n",
            "ModuleNotFoundError",
        ),
        ("from thzdaq import value\nx = value('X', None)\n", "give a number"),
        ("from thzdaq import device\nd = device('D', 'Nothing')\n", "No capability"),
    ],
)
def test_a_script_that_cannot_be_described_is_listed_with_why(lab, text, told):
    saved(lab, "broken", text)
    found = summary(lab, "broken")
    assert told in found.error, found.error
    with pytest.raises(LabError) as caught:
        lab.call(DescribeProcedure(procedure="custom.broken"))
    assert caught.value.code == ErrorCode.NOT_FOUND and told in caught.value.message


def test_clients_hear_the_library_change(lab):
    heard = []
    stop = lab.subscribe(heard.append)
    try:
        path = saved(lab, "pv", PV)

        def told():
            changes = bodies(heard, ProceduresChanged)
            return changes and changes[-1].procedures

        wait_for(lambda: any(p.name == "custom.pv" for p in told() or ()), 10)
        # All of them now, the built-in ones too: clients replace their list
        assert told() == lab.call(ListProcedures())
        path.unlink()
        wait_for(lambda: not any(p.name == "custom.pv" for p in told()), 10)
        assert told() == lab.call(ListProcedures())
    finally:
        stop()


def test_a_declared_value_is_parsed_as_a_run_takes_it(lab):
    def parsed(default, unit="", **given):
        declared = ValueDeclared("x", "X", default, unit, **given)
        found = lab.call(ParseValue(value=declared))
        return found.value, found.unit, found.kind

    assert parsed("0:7:351", "mV") == (
        {"start": 0.0, "stop": 0.007, "points": 351}, "V", "sweep",
    )  # fmt: skip
    assert parsed(10, "ms") == (pytest.approx(0.01), "s", "float")
    assert parsed(101) == (101, "", "int")
    assert parsed(True) == (True, "", "bool")
    assert parsed("hot", choices=("hot", "cold")) == ("hot", "", "choice")
    assert parsed([4, 6], "GHz") == ([4e9, 6e9], "Hz", "float_list")
    assert parsed("a label") == ("a label", "", "text")
    with pytest.raises(LabError) as caught:
        parsed(9, "mV", maximum=5)
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS


def test_a_run_gives_its_script_the_values_chosen(lab):
    saved(lab, "told", TOLD)
    heard = []
    stop = lab.subscribe(heard.append)
    try:
        run = lab.call(
            StartMeasurement(
                procedure="custom.told", typed={"voltage": "1:2:11", "settle": "5"}
            )
        )
        assert (run.procedure, run.title, run.status) == (
            "custom.told", "Told", "running",
        )  # fmt: skip
        done = lab.call(WaitMeasurement(id=run.id, timeout=30))
    finally:
        stop()
    assert done.status == "completed", done.error
    printed = "".join(part.text for part in bodies(heard, ScriptOutput))
    told, inputs = printed.splitlines()
    assert told == (
        "Swept(start=0.001, stop=0.002, points=11, unit='V') 0.005 s ('hot', 'cold')"
    )
    assert json.loads(inputs)["values"]["settle"] == {
        "value": 0.005, "unit": "s", "kind": "float",
    }  # fmt: skip
    measured = read_measurement(done.path)
    assert measured.procedure == "custom.told"
    assert measured.parameters["voltage"] == {
        "start": 0.001,
        "stop": 0.002,
        "points": 11,
    }
    assert measured.metadata["script"]["text"] == TOLD
    (script,) = lab.call(ListScripts())
    assert (script.by, script.name, script.measurement) == ("test", "told", run.id)


def test_a_run_whose_script_fails_fails_with_its_traceback(lab):
    saved(lab, "fails", '"""Fails"""\nraise RuntimeError("no bench today")\n')
    run = lab.call(StartMeasurement(procedure="custom.fails"))
    done = lab.call(WaitMeasurement(id=run.id, timeout=30))
    assert done.status == "failed" and "exited with code 1" in done.error
    traceback = read_measurement(done.path).metadata.get("traceback", "")
    assert "RuntimeError: no bench today" in (done.error + traceback)


def test_a_cancel_ends_its_script(lab):
    lab.assembled.scripts.grace = 0.2
    saved(lab, "slow", '"""Slow"""\nimport time\ntime.sleep(60)\n')
    run = lab.call(StartMeasurement(procedure="custom.slow"))
    wait_for(lambda: lab.call(ListScripts()), 10)
    lab.call(CancelMeasurement(id=run.id))
    done = lab.call(WaitMeasurement(id=run.id, timeout=30))
    assert done.status == "cancelled"
    wait_for(lambda: lab.call(ListScripts())[0].status == "stopped", 10)


def test_an_unknown_or_broken_one_does_not_start(lab):
    saved(lab, "broken", "x = (\n")
    for name in ("custom.nothing", "custom.broken"):
        with pytest.raises(LabError) as caught:
            lab.call(StartMeasurement(procedure=name))
        assert caught.value.code == ErrorCode.NOT_FOUND, name


DRAFT = """from thzdaq import connect, device, value
import os

bias = device("SIS bias", kind="sis_bias")
voltage = value("Bias voltage", "0:9:11", unit="mV")
lab = connect()
pm = lab["power_meter_9"]
with lab.measurement("x", devices=[bias]) as m:
    for v in m.sweep(voltage):
        bias.voltage_set = v
        m.record("t", v=bias.voltge, p=undefined)
"""


def test_the_library_is_listed_read_and_written(lab):
    saved(lab, "pv", PV)
    listed = lab.call(ListCustom())
    assert listed.folder == str(library(lab))
    (pv,) = listed.measurements
    assert (pv.name, pv.procedure, pv.title, pv.error) == (
        "pv", "custom.pv", "P-V hot/cold", "",
    )  # fmt: skip
    assert lab.call(ReadCustom(script="pv")).text == PV
    checked = lab.call(WriteCustom(script="told", text=TOLD))
    assert (library(lab) / "told.py").read_text(encoding="utf-8") == TOLD
    assert checked.procedure.name == "custom.told" and not checked.problems
    assert summary(lab, "told").title == "Told"
    for operation, code in (
        (WriteCustom(script="2bad", text=""), ErrorCode.INVALID_ARGUMENTS),
        (ReadCustom(script="nothing"), ErrorCode.NOT_FOUND),
    ):
        with pytest.raises(LabError) as caught:
            lab.call(operation)
        assert caught.value.code == code


def test_a_check_tells_what_is_wrong_and_where(lab):
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {
        "limits": {"sis_bias_1": {"voltage_set": {"min": -5e-3, "max": 5e-3}}}
    }
    lab.call(UpdateStation(profile=profile))
    checked = lab.call(CheckCustom(script="draft", text=DRAFT))
    found = {(p.line, p.kind): p.text for p in checked.problems}
    assert "'os' imported but unused" in found[2, "names"]
    assert "no device 'power_meter_9'" in found[7, "bench"]
    assert "goes beyond -0.005..0.005 V" in found[9, "bench"]
    assert "has no quantity or action 'voltge'" in found[11, "bench"]
    assert "undefined name 'undefined'" in found[11, "names"]
    assert checked.procedure.name == "custom.draft"
    assert not (library(lab) / "draft.py").exists()  # a check writes nothing
    broken = lab.call(CheckCustom(script="draft", text="x = (\n"))
    assert [p.kind for p in broken.problems] == ["syntax"] and not broken.procedure
    late = lab.call(
        CheckCustom(
            script="draft",
            text=DRAFT.replace("pm = lab", "t = value('T', 1)\npm = lab"),
        )
    )
    assert any("after connect()" in p.text and p.line == 7 for p in late.problems)


def test_an_agents_write_is_shown_to_a_person_first(lab_as, lab):
    saved(lab, "told", TOLD)
    window = Window(lab_as(GUI))
    try:
        changed = TOLD.replace('"Settle", 10', '"Settle", 20')
        thread, done = calling(
            lab_as("mcp:claude"), WriteCustom(script="told", text=changed)
        )
        approval = window.asked()
        assert approval.title == "Change measurement told"
        assert '-settle = value("Settle", 10, unit="ms")' in approval.text
        assert '+settle = value("Settle", 20, unit="ms")' in approval.text
        window.answer(allowed=False, text="keep 10 ms")
        thread.join(5)
        assert done["error"].code == ErrorCode.DENIED
        assert (library(lab) / "told.py").read_text(encoding="utf-8") == TOLD
    finally:
        window.stop()


GAUGE = '''"""Degas"""
from thzdaq import connect, instrument, reading, setting, value

gauge = instrument(
    "gauge_1", driver="generic.scpi", connection="tcp://169.254.0.50:5025",
    pressure=reading("PR1?", unit="Pa", parse=r"P=([0-9.Ee+-]+)", scale=100),
    level=setting("VOLT?", "VOLT {:.6f}", unit="V", minimum=0, maximum=5),
)
power = value("Heater", 2.5, unit="V")
lab = connect()
raise SystemExit("never here when described")
'''


def test_an_instrument_is_declared_without_touching_the_profile(lab, lab_as):
    window = Window(lab_as(GUI))
    try:
        before = lab.call(GetStation()).profile
        saved(lab, "degas", GAUGE)
        found = summary(lab, "degas")
        assert not found.error, found.error
        info = lab.call(DescribeProcedure(procedure="custom.degas"))
        assert [p.name for p in info.parameters] == ["power"] and not info.slots
        checked = lab.call(CheckCustom(script="degas"))
        (told,) = [p for p in checked.problems if p.kind == "bench"]
        assert told.line == 4 and "gauge_1 is not in the profile" in told.text
        assert lab.call(GetStation()).profile == before and not window.waiting()
    finally:
        window.stop()
