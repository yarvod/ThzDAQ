"""Every example runs as the bench's own measurement (custom.<name>) on a daemon
of the simulators, as a window's Start or thzdaq run custom.x --set runs it:
its form given short values, its script started by the daemon, its session
taken over by the script. One runs as it is too (python x.py, here thzdaq
script start): its defaults are parsed by the daemon."""

import pytest
from lab_helpers import Window, wait_for
from test_process import start
from thzdaq_api import examples
from thzdaq_api.custom import LIBRARY
from thzdaq_api.devices import ReadDevice, SetQuantity
from thzdaq_api.host import script_python
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import (
    CancelMeasurement,
    ListRuns,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.origins import GUI
from thzdaq_api.remote import RemoteLab
from thzdaq_api.scripts import ListScripts, ReadScriptLog, StartScript

# The form's values that make each short
SHORT = {
    "sweep": {"voltage": "0:7:21", "settle": "1"},
    "hot_cold": {"voltage": "0:7:21", "settle": "1", "load_settle": "0.05"},
    "hot_cold_grid": {
        "voltage": "0:7:11",
        "angle": "0:90:3",
        "settle": "1",
        "load_settle": "0.05",
        "grid_settle": "0.05",
    },
    "monitor": {"interval": "0.05", "duration": "0.5"},
    "iv_analysis": {"voltage": "0:7:41"},
    "map": {"voltage": "0:7:5", "current": "0:10:3", "settle": "1"},
    "raw_instrument": {"level": "0:5:6", "settle": "1"},
}
# The devices of the form, as a window or the command line fills the slots
BENCH = {
    "bias": "sis_bias_1", "detector": "power_meter_1", "load": "chopper_1",
    "coil": "sis_coil_1", "grid": "grid_1",
}  # fmt: skip
DEVICES = {
    "sweep": ("bias", "detector"),
    "hot_cold": ("bias", "detector", "load"),
    "hot_cold_grid": ("bias", "detector", "load", "grid"),
    "monitor": ("detector", "bias"),
    "iv_analysis": ("bias",),
    "map": ("bias", "coil", "detector"),
    "raw_instrument": (),
}
# The table each measures (in its own measurement), at least how many
# records, what it prints at the end
MEASURES = {
    "sweep": ("iv", 21, "completed"),
    "hot_cold": ("pv", 42, "Tn "),
    "hot_cold_grid": ("pv", 66, "completed"),
    "monitor": ("samples", 3, "readings in"),
    "iv_analysis": (None, 0, "Vgap = "),  # its records are the I-V run's
    "map": ("map", 15, "completed"),
    "raw_instrument": ("levels", 6, "SimGenericScpi"),
}
# What a person in the window allows each to do, in order
ASKED = {"raw_instrument": ["source_1 · add to the profile", "source_1 · raw write"]}


def ended(lab, id, timeout=60):
    info = lab.call(WaitMeasurement(id=id, timeout=0))
    wait_for(
        lambda: lab.call(WaitMeasurement(id=id, timeout=1)).status != "running",
        timeout=timeout,
    )
    return lab.call(WaitMeasurement(id=id, timeout=0)) if info else info


def log_of(lab, name):
    (script,) = [s for s in lab.call(ListScripts()) if s.name == name]
    wait_for(
        lambda: next(s for s in lab.call(ListScripts()) if s.id == script.id).status
        != "running",
        timeout=30,
    )
    return lab.call(ReadScriptLog(id=script.id)).text


def bias_now(lab):
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    return reading.values["voltage_set"]


def test_every_example_is_tested():
    assert (
        sorted(SHORT) == sorted(DEVICES) == sorted(e.name for e in examples.examples())
    )


@pytest.mark.parametrize("name", sorted(SHORT))
def test_an_example_runs_as_the_benchs_own_measurement(home, tmp_path, name):
    lab = start(home)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    examples.create(name, home / LIBRARY)
    workspace = tmp_path / "experiment"
    workspace.mkdir()
    window = Window(RemoteLab(lab.host, GUI, GUI))
    run = lab.call(
        StartMeasurement(
            procedure=f"custom.{name}", typed=SHORT[name], workspace=str(workspace),
            devices={slot: BENCH[slot] for slot in DEVICES[name]},
        )  # fmt: skip
    )
    asked = ASKED.get(name, [])
    assert window.allow(len(asked)) == asked
    done = ended(lab, run.id)
    assert not window.waiting()
    window.stop()
    log = log_of(lab, name)
    assert done.status == "completed", (done.error, log)
    table, rows, told = MEASURES[name]
    assert told in log
    measurement = read_measurement(done.path)
    assert measurement.procedure == f"custom.{name}"
    assert measurement.metadata["script"]["text"] == examples.example(name).text
    if table is not None:
        assert len(measurement.records(table)) >= rows
    assert bias_now(lab) == pytest.approx(1e-3)  # set back


def test_a_monitor_runs_until_it_is_stopped(home, tmp_path):
    lab = start(home)
    examples.create("monitor", home / LIBRARY)
    run = lab.call(
        StartMeasurement(
            procedure="custom.monitor", typed={"interval": "0.05", "duration": "0"},
            devices={slot: BENCH[slot] for slot in DEVICES["monitor"]},
        )  # fmt: skip
    )
    wait_for(
        lambda: lab.call(WaitMeasurement(id=run.id, timeout=0)).done >= 3, timeout=30
    )
    lab.call(CancelMeasurement(id=run.id))
    done = ended(lab, run.id)
    log = log_of(lab, "monitor")
    assert done.status == "cancelled", (done.error, log)
    assert "cancelled" in log
    assert len(read_measurement(done.path).records("samples")) >= 3


def test_an_example_runs_as_it_is(home, tmp_path):
    lab = start(home)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    path = examples.create("sweep", tmp_path / "scripts")
    path.write_text(
        path.read_text(encoding="utf-8").replace('"0:7:351"', '"0:7:11"'),
        encoding="utf-8",
    )
    lab.call(StartScript(path=str(path), python=script_python()))
    log = log_of(lab, "sweep")
    (run,) = lab.call(ListRuns())
    assert run.status == "completed", (run.error, log)
    measurement = read_measurement(run.path)
    assert measurement.procedure == "script:bias_sweep"
    assert len(measurement.records("iv")) == 11
    assert measurement.parameters["voltage"] == {
        "start": 0.0, "stop": 0.007, "points": 11,
    }  # fmt: skip
    assert measurement.devices["sis_bias_1"]  # the first that suits the slot
    assert bias_now(lab) == pytest.approx(1e-3)
