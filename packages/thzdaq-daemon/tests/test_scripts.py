"""A script the daemon runs, end to end: started and stopped from the command
line, measuring through the client a script imports (thzdaq), restored by the
daemon when it is stopped."""

import pytest
from lab_helpers import wait_for
from test_process import start
from thzdaq_api.devices import ReadDevice, SetQuantity
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import ListRuns
from thzdaq_api.origins import AGENT_SHELLS
from thzdaq_api.scripts import ListScripts, ReadScriptLog

SCAN = """\
import sys
from thzdaq import connect

lab = connect()
bias = lab["sis_bias_1"]
with lab.measurement("scan", devices=[bias]) as m:
    m.restore(bias, "voltage_set")
    for v in m.sweep(f"2:3:{sys.argv[1]}", unit="mV"):
        bias.voltage_set = v
        m.record("scan", voltage_set=v, voltage=bias.voltage)
        m.progress()
    print("swept", flush=True)
    while True:
        m.sleep(0.1)  # until it is stopped
print("ended", m.run.status)
"""


@pytest.fixture
def thzdaq(capsys, monkeypatch):
    """thzdaq ARGS against the simulator's daemon, as a person types it."""
    from thzdaq_cli.app import main

    for name in AGENT_SHELLS:
        monkeypatch.delenv(name, raising=False)

    def run(*argv):
        code = main(["--simulate", *argv])
        out, err = capsys.readouterr()
        return code, out, err

    return run


def logged(lab, id):
    return lab.call(ReadScriptLog(id=id)).text


def test_a_script_started_from_the_command_line_measures_and_is_stopped(
    home, tmp_path, thzdaq
):
    lab = start(home)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    file = tmp_path / "scan.py"
    file.write_text(SCAN)
    code, out, err = thzdaq(
        "script", "start", str(file), "--allow", "set:sis_bias_1",
        "--workspace", str(tmp_path), "--", "3",
    )  # fmt: skip
    assert code == 0, err
    (script,) = lab.call(ListScripts())
    assert f"script {script.id} scan: running" in out
    wait_for(lambda: "swept" in logged(lab, script.id), timeout=30)

    code, out, err = thzdaq("script", "stop", str(script.id))
    assert code == 0 and "stopped (exit code 0)" in out, err + logged(lab, script.id)
    assert "ended cancelled" in logged(lab, script.id)
    (run,) = lab.call(ListRuns())
    assert (run.procedure, run.status) == ("script:scan", "cancelled")
    assert run.origin == f"script:scan@{script.id}"
    saved = read_measurement(run.path)
    assert len(saved.records("scan")) == 3
    assert saved.metadata["allowed"][0]["allow"] == ["set:sis_bias_1"]
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    assert reading.values["voltage_set"] == pytest.approx(1e-3)  # restored

    code, out, _ = thzdaq("script", "logs", str(script.id))
    assert out.splitlines() == ["swept", "ended cancelled"]
    code, out, _ = thzdaq("script", "list")
    assert "scan" in out and "stopped" in out
