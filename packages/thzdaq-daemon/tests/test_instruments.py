"""An instrument without a driver, declared in a script (instrument(...)), end
to end on a daemon of the simulators: a person's script puts it into the
profile once a person allows it, and measures with it through raw commands
named by reading and setting; an agent's script is refused."""

import pytest
from lab_helpers import Window, calling
from test_examples import log_of
from test_process import start
from thzdaq_api.host import script_python
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import ListRuns
from thzdaq_api.origins import GUI
from thzdaq_api.remote import RemoteLab
from thzdaq_api.scripts import ListScripts, StartScript
from thzdaq_core.adapters.yaml_profiles import load_station, versions

DEGAS = """\
from thzdaq import LabError, connect, instrument, reading, setting

gauge = instrument(
    "gauge_1", driver="generic.scpi", connection="tcp://169.254.0.50:5025",
    level=setting("VOLT?", "VOLT {:.6f}", unit="V", minimum=0, maximum=5),
    state=reading("OUTP?", parse={"ON": True, "OFF": False}),
)
lab = connect()
gauge.raw("OUTP ON")  # outside a measurement: asked
with lab.measurement("degas", devices=[gauge]) as m:
    for v in (1.0, 2.5):
        gauge.level = v  # the first write asked, the second goes
        m.record("levels", level=gauge.level, on=gauge.state)
    try:
        gauge.level = 25
    except LabError as e:
        print("refused:", e.message)
print(gauge.raw("*IDN?"))
"""


@pytest.fixture
def window(home):
    """A person's window on the daemon, answering what waits."""
    lab = start(home)
    window = Window(RemoteLab(lab.host, GUI, GUI))
    yield window
    window.stop()


def test_a_persons_script_adds_its_instrument_and_measures_with_it(
    home, tmp_path, window
):
    lab = start(home)
    path = tmp_path / "degas.py"
    path.write_text(DEGAS, encoding="utf-8")
    lab.call(
        StartScript(path=str(path), python=script_python(), workspace=str(tmp_path))
    )
    titles = window.allow(3)
    assert titles == [
        "gauge_1 · add to the profile",
        "gauge_1 · raw write",
        "gauge_1 · raw write",
    ]
    log = log_of(lab, "degas")
    assert "refused: gauge_1/level: 25 V is beyond 0..5 V" in log, log
    assert "THZDAQ,SimGenericScpi" in log and not window.waiting()
    profile = load_station(home / "bench.yaml")
    assert profile.instruments["gauge_1"].connection.port == 5025
    assert len(versions(home / "bench.yaml")) == 1
    (run,) = lab.call(ListRuns())
    assert run.status == "completed", (run.error, log)
    saved = read_measurement(run.path)
    assert saved.column("levels", "level") == [1.0, 2.5]
    assert saved.column("levels", "on") == [True, True]
    level = saved.tables["levels"].get_column("level")
    assert (level.unit, level.source) == ("V", "gauge_1/level")
    assert saved.metadata["allowed"][0]["allow"] == ["raw:gauge_1"]


def test_an_agents_script_is_refused_and_told_who_adds_it(home, tmp_path, window):
    lab = start(home)
    path = tmp_path / "degas.py"
    path.write_text(DEGAS, encoding="utf-8")
    agent = RemoteLab(lab.host, "mcp:claude", "mcp")
    start_script = StartScript(
        path=str(path), python=script_python(), workspace=str(tmp_path)
    )
    thread, done = calling(agent, start_script)
    (started,) = window.allow(1)  # its start; the profile is not asked
    assert started.startswith("Run script")
    thread.join(10)
    log = log_of(lab, "degas")
    assert "an agent's script does not change the profile" in log, log
    assert "Setup → Add instrument → Generic (raw)" in log
    (script,) = lab.call(ListScripts())
    assert script.exit_code != 0 and not window.waiting()
    assert "gauge_1" not in load_station(home / "bench.yaml").instruments
