"""The Python a workspace names (thzdaq.toml) runs its scripts on a daemon of
the simulators: the bench's own measurement started there, and thzdaq script
start there. The workspace's Python is a venv of its own made here, which
reaches thzdaq of this environment through a .pth file."""

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from test_examples import ended, log_of
from test_process import start
from thzdaq_api.custom import LIBRARY
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.interpreters import python_in
from thzdaq_api.measurements import ListRuns, StartMeasurement
from thzdaq_api.scripts import ListScripts
from thzdaq_api.workspace import create

WHERE = '''\
"""Where it runs."""
import sys

from thzdaq import connect, value

points = value("Points", 2)
connect()
print("prefix", sys.prefix, flush=True)
'''


@pytest.fixture
def workspace(tmp_path) -> Path:
    """A workspace whose thzdaq.toml names its .venv: a venv with thzdaq."""
    folder = tmp_path / "experiment"
    create(folder, python=".venv")
    venv = folder / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
    )
    done = subprocess.run(
        [str(python_in(venv)), "-c",
         "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    ours = sysconfig.get_paths()["purelib"]
    (Path(done.stdout.strip()) / "ours.pth").write_text(
        f"import site; site.addsitedir({ours!r})\n"
    )
    return folder


def ran_in(log: str) -> Path:
    (line,) = [line for line in log.splitlines() if line.startswith("prefix ")]
    return Path(line.split(" ", 1)[1]).resolve()


def test_the_benchs_own_measurement_runs_with_its_workspaces_python(home, workspace):
    lab = start(home)
    (home / LIBRARY).mkdir()
    (home / LIBRARY / "where.py").write_text(WHERE)
    run = lab.call(StartMeasurement(procedure="custom.where", workspace=str(workspace)))
    done = ended(lab, run.id)
    log = log_of(lab, "where")
    assert done.status == "completed", (done.error, log)
    assert ran_in(log) == (workspace / ".venv").resolve()
    (script,) = lab.call(ListScripts())
    assert script.command[0] == str(python_in(workspace / ".venv"))


def test_a_script_started_in_the_workspace_runs_with_its_python(
    home, workspace, thzdaq
):
    lab = start(home)
    file = workspace / "scripts" / "where.py"
    file.write_text(WHERE)
    code, _, err = thzdaq("script", "start", str(file), "--workspace", str(workspace))
    assert code == 0, err
    assert ran_in(log_of(lab, "where")) == (workspace / ".venv").resolve()


def test_a_python_that_is_not_there_refuses_the_start(home, tmp_path):
    lab = start(home)
    (home / LIBRARY).mkdir()
    (home / LIBRARY / "where.py").write_text(WHERE)
    create(tmp_path / "broken", python=".venv")
    with pytest.raises(LabError) as e:
        lab.call(
            StartMeasurement(
                procedure="custom.where", workspace=str(tmp_path / "broken")
            )
        )
    assert e.value.code == ErrorCode.NOT_FOUND and "'.venv'" in str(e.value)
    assert lab.call(ListRuns()) == () and lab.call(ListScripts()) == ()
