"""The P-V hot/cold over the grid's angles (docs/daemon.md, M3's acceptance)
as a person runs it: the example started as a script by the command line,
seen and cancelled from another terminal; the daemon then sets the bias and
the grid back and turns to the cold load."""

import pytest
from lab_helpers import wait_for
from test_process import start
from thzdaq_api import examples
from thzdaq_api.devices import CallAction, ReadDevice, SetQuantity
from thzdaq_api.measurement_file import CANCELLED, read_measurement
from thzdaq_api.measurements import ListRuns, WaitMeasurement
from thzdaq_api.scripts import RUNNING, ListScripts, ReadScriptLog

BIAS, DETECTOR, LOAD, GRID = "sis_bias_1", "power_meter_1", "chopper_1", "grid_1"
POINTS = 21  # of each bias sweep
# The example's defaults made short; the grid's settle stays long enough for
# the cancel to land well before the last angle
SHORT = {
    '"0:7:351"': f'"0:7:{POINTS}"',
    'value("Grid settle", 1,': 'value("Grid settle", 0.5,',
    'value("Load settle", 2,': 'value("Load settle", 0.05,',
    'value("Settle", 10,': 'value("Settle", 1,',
}


def value(lab, ref, key):
    return lab.call(ReadDevice(ref=ref, keys=(key,))).values[key]


def test_the_grid_hot_cold_runs_as_a_script_and_is_cancelled(home, tmp_path, thzdaq):
    lab = start(home)
    lab.call(SetQuantity(ref=BIAS, key="voltage_set", value="1mV"))
    lab.call(SetQuantity(ref=GRID, key="angle", value="15"))
    lab.call(CallAction(ref=LOAD, action="to_hot"))
    path = examples.create("hot_cold_grid", tmp_path / "scripts")
    text = path.read_text(encoding="utf-8")
    for default, short in SHORT.items():
        assert default in text
        text = text.replace(default, short)
    path.write_text(text, encoding="utf-8")

    allowed = [f"--allow=set:{ref}" for ref in (BIAS, DETECTOR, LOAD, GRID)]
    code, out, err = thzdaq(
        "script", "start", str(path), *allowed, "--workspace", str(tmp_path)
    )
    assert code == 0, err
    (script,) = lab.call(ListScripts())
    wait_for(lambda: lab.call(ListRuns()), timeout=30)
    (run,) = lab.call(ListRuns())
    # into the second angle: the grid has turned
    wait_for(
        lambda: lab.call(WaitMeasurement(id=run.id, timeout=0)).done > 2 * POINTS,
        timeout=60,
    )

    code, out, err = thzdaq("status")
    assert code == 0, err
    assert f"script:hot_cold_grid@{script.id}" in out and str(run.id) in out
    code, out, err = thzdaq("cancel", str(run.id))
    assert code == 0, err

    wait_for(lambda: lab.call(ListScripts())[0].status != RUNNING, timeout=30)
    log = lab.call(ReadScriptLog(id=script.id)).text
    assert f"#{run.id} {CANCELLED}" in log, log
    done = lab.call(WaitMeasurement(id=run.id, timeout=0))
    assert done.status == CANCELLED
    angles = {row["angle"] for row in read_measurement(done.path).records("pv")}
    assert {0.0, 10.0} <= angles and 90.0 not in angles
    assert value(lab, BIAS, "voltage_set") == pytest.approx(1e-3)
    assert value(lab, GRID, "angle") == pytest.approx(15.0)
    assert value(lab, LOAD, "load_state") == "cold"
