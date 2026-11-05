"""Every template of a new script runs as the daemon runs a script, on the
simulators of the example profile, made short for a test: its sizes are the
only lines changed. Each is allowed in advance what a person would allow it
in the window."""

import pytest
from lab_helpers import wait_for
from test_process import start
from thzdaq_api import templates
from thzdaq_api.devices import ReadDevice, SetQuantity
from thzdaq_api.host import script_python
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import ListRuns
from thzdaq_api.scripts import (
    Grant,
    ListScripts,
    ReadScriptLog,
    StartScript,
    StopScript,
)
from thzdaq_api.workspace import SCRIPT_FOLDER

# A template's lines as it is, and as the test runs it
SHORT = {
    "sweep": {'VOLTAGE = "0:7:351"': 'VOLTAGE = "0:7:21"'},
    "hot_cold": {
        'VOLTAGE = "0:7:351"': 'VOLTAGE = "0:7:21"',
        "LOAD_SETTLE_S = 2.0": "LOAD_SETTLE_S = 0.05",
    },
    "monitor": {"INTERVAL_S = 1.0": "INTERVAL_S = 0.05", "DURATION_S = 0": ""},
    "iv_analysis": {'VOLTAGE = "0:7:351"': 'VOLTAGE = "0:7:141"'},
}
# What a person allows each in advance
ALLOW = {
    "sweep": ("set:sis_bias_1", "set:power_meter_1"),
    "hot_cold": ("set:sis_bias_1", "set:power_meter_1", "call:chopper_1"),
    "monitor": ("set:sis_bias_1", "set:power_meter_1"),
    "iv_analysis": ("run:sis.iv_curve",),
}
# The table each measures, at least how many records, what it prints at the end
MEASURES = {
    "sweep": ("iv", 21, "completed"),
    "hot_cold": ("pv", 42, "Tn "),
    "monitor": ("samples", 3, "readings in"),
    "iv_analysis": ("iv", 141, "Vgap = "),
}


def shortened(name: str, folder, duration: str = "0.5"):
    """The template as a script in folder, its sizes made short."""
    path = templates.create(name, folder)
    text = path.read_text(encoding="utf-8")
    for line, short in SHORT[name].items():
        assert line in text, f"{name}: {line!r} is no longer in the template"
        text = text.replace(line, short or f"DURATION_S = {duration}")
    path.write_text(text, encoding="utf-8")
    return path


def started(lab, path, name, workspace):
    return lab.call(
        StartScript(
            path=str(path),
            python=script_python(),
            workspace=str(workspace),
            allow=tuple(Grant.parse(grant) for grant in ALLOW[name]),
        )
    )


def ended(lab, id, timeout=60):
    def info():
        return next(s for s in lab.call(ListScripts()) if s.id == id)

    wait_for(lambda: info().status != "running", timeout=timeout)
    return info()


def bias_now(lab):
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    return reading.values["voltage_set"]


def test_every_template_is_tested():
    assert sorted(SHORT) == sorted(t.name for t in templates.templates())


@pytest.mark.parametrize("name", sorted(SHORT))
def test_a_template_runs_on_simulators(home, tmp_path, name):
    lab = start(home)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    workspace = tmp_path / "experiment"
    script = started(lab, shortened(name, workspace / SCRIPT_FOLDER), name, workspace)
    done = ended(lab, script.id)
    log = lab.call(ReadScriptLog(id=script.id)).text
    assert (done.status, done.exit_code) == ("exited", 0), log
    table, rows, told = MEASURES[name]
    assert told in log
    (run,) = [r for r in lab.call(ListRuns()) if r.workspace == str(workspace)]
    assert run.status == "completed", run.error
    measurement = read_measurement(run.path)
    assert len(measurement.records(table)) >= rows
    if name != "iv_analysis":  # a script's own: its text is kept with it
        kept = measurement.metadata["script"]
        assert kept["path"] == f"{SCRIPT_FOLDER}/{name}.py"
        assert kept["text"] == (workspace / kept["path"]).read_text(encoding="utf-8")
    assert bias_now(lab) == pytest.approx(1e-3)  # set back


def test_a_monitor_runs_until_it_is_stopped(home, tmp_path):
    lab = start(home)
    workspace = tmp_path / "experiment"
    path = shortened("monitor", workspace / SCRIPT_FOLDER, duration="0")
    script = started(lab, path, "monitor", workspace)

    def measured():
        runs = lab.call(ListRuns())
        return runs and runs[0].done >= 3

    wait_for(measured, timeout=30)
    stopped = lab.call(StopScript(id=script.id))
    log = lab.call(ReadScriptLog(id=script.id)).text
    assert (stopped.status, stopped.exit_code) == ("stopped", 0), log
    (run,) = lab.call(ListRuns())
    assert run.status == "cancelled" and "cancelled" in log
    assert len(read_measurement(run.path).records("samples")) >= 3
