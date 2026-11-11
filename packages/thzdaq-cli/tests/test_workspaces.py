"""thzdaq in workspaces: found up from here, made by init, opened by gui."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from thzdaq_api import host
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import PROFILE, read_measurement
from thzdaq_api.workspace import FILE, WORKSPACE_ENV, create, read

FAST = ["--set", "settle_time=0", "--set", "first_point_delay=0"]
EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


def run_iv(thzdaq, *more):
    return thzdaq(
        "--json", "run", "sis.current_vs_voltage", "--device", "bias=sis_bias_1",
        "--set", "voltage=0:1:3", *FAST, *more,
    )  # fmt: skip


def test_a_run_goes_to_the_workspace_found_up_from_here(thzdaq, tmp_path, monkeypatch):
    create(tmp_path / "experiment", "bench")
    monkeypatch.chdir(tmp_path / "experiment" / "scripts")
    code, out, err = run_iv(thzdaq)
    assert code == 0, err
    done = json.loads(out.splitlines()[-1])["run"]  # as it ended
    assert done["workspace"] == str((tmp_path / "experiment").resolve())
    assert Path(done["path"]).parents[1] == (tmp_path / "experiment" / "data")
    assert "expects the profile" not in err  # the daemon works with bench.yaml


def test_without_a_workspace_the_daemon_writes_to_its_own(thzdaq, tmp_path):
    code, out, err = run_iv(thzdaq)
    assert code == 0, err
    ended = json.loads(out.splitlines()[-1])["run"]
    assert ended["workspace"] == str(tmp_path.resolve())  # its home


def test_a_workspace_that_expects_another_profile_is_told(thzdaq, tmp_path):
    create(tmp_path / "experiment", "lab")
    code, _, err = run_iv(thzdaq, "--workspace", str(tmp_path / "experiment"))
    assert code == 0  # told, not refused
    assert "expects the profile 'lab'" in err and "'bench'" in err
    assert "thzdaq station load lab" in err


def test_init_makes_a_workspace_for_the_daemons_profile(thzdaq, tmp_path):
    code, out, err = thzdaq("init", "experiment")
    assert code == 0, err
    assert out.splitlines()[0] == f"written {FILE}: expects the profile 'bench'"
    assert read(tmp_path / "experiment").station == "bench"
    assert (tmp_path / "experiment" / "scripts").is_dir()
    code, out, _ = thzdaq("init", "experiment", "--station", "other")
    assert out.startswith(f"kept {FILE}") and "'bench'" in out


def test_init_with_agents_writes_what_they_read(thzdaq, tmp_path):
    code, out, err = thzdaq("--json", "init", "--station", "lab", "--agents")
    assert code == 0, err
    told = json.loads(out)
    assert told["station"] == "lab" and told["files"] == {FILE: "written"}
    assert told["agents"]["files"][".mcp.json"] == "written"
    assert (tmp_path / "AGENTS.md").exists() and (tmp_path / ".mcp.json").exists()


def test_init_without_a_daemon_expects_no_profile(tmp_path, monkeypatch, capsys):
    from thzdaq_cli.app import main

    def none_runs(simulate, autostart, kind, station):
        assert not autostart  # init starts no daemon
        raise LabError(ErrorCode.UNREACHABLE, "No daemon runs")

    monkeypatch.chdir(tmp_path)
    assert main(["init"], connect=none_runs) == 0
    assert "expects no profile" in capsys.readouterr().out
    assert read(tmp_path).station == ""


def test_a_daemon_started_in_a_workspace_loads_its_profile(tmp_path, monkeypatch):
    from thzdaq_cli.app import main

    create(tmp_path, "lab")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    started = []

    def starting(simulate, autostart, kind, station):
        started.append(station)
        raise LabError(ErrorCode.UNREACHABLE, "No daemon runs")

    assert main(["devices"], connect=starting) == 3
    assert started == ["lab"]


def test_gui_opens_the_window_in_the_workspace_here(thzdaq, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(host, "window_command", lambda: ["ThzDAQ"])
    monkeypatch.setattr(host, "start_apart", opened.append)
    code, out, _ = thzdaq("--simulate", "gui")
    assert code == 0 and out.strip() == "ThzDAQ opens in its default workspace"
    create(tmp_path / "experiment")
    monkeypatch.chdir(tmp_path / "experiment")
    code, out, _ = thzdaq("gui")
    folder = str((tmp_path / "experiment").resolve())
    assert opened == [
        ["ThzDAQ", "--simulate"],
        ["ThzDAQ", "--workspace", folder],
    ]
    assert out.strip() == f"ThzDAQ opens in {folder}"


def test_a_profile_is_loaded_by_its_name_or_its_path_here(
    thzdaq, lab, tmp_path, monkeypatch
):
    (tmp_path / "stations").mkdir()
    shutil.copy(tmp_path / "bench.yaml", tmp_path / "stations" / "other.yaml")
    code, out, err = thzdaq("--json", "station", "load", "other")
    assert code == 0, err
    assert json.loads(out)["path"] == str((tmp_path / "stations/other.yaml").resolve())
    monkeypatch.chdir(tmp_path / "stations")
    code, out, err = thzdaq("--json", "station", "load", "../bench.yaml")
    assert code == 0, err
    assert json.loads(out)["path"] == str((tmp_path / "bench.yaml").resolve())


def test_a_real_daemon_started_for_a_workspace_loads_its_profile(tmp_path):
    """The command starts the simulator's daemon in the program's folder (from
    sources: where it runs, here tmp_path with its stations/) with the
    profile the workspace names; the measurement keeps a copy of it."""
    (tmp_path / "stations").mkdir()
    shutil.copy(EXAMPLE, tmp_path / "stations" / "2sb.yaml")
    create(tmp_path / "experiment", "2sb")
    env = {**os.environ, "THZDAQ_DAEMON_DIR": str(tmp_path / "daemon")}
    env.pop(WORKSPACE_ENV, None)

    def thzdaq(*argv):
        return subprocess.run(
            [sys.executable, "-m", "thzdaq_cli", "--simulate", "--json", *argv],
            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
        )  # fmt: skip

    try:
        done = thzdaq(
            "run", "sis.current_vs_voltage", "--device", "bias=sis_bias_1",
            "--set", "voltage=0:1:3", *FAST, "--workspace", "experiment",
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert "daemon started" in done.stderr and "expects" not in done.stderr
        shown = json.loads(thzdaq("station", "show").stdout)
        assert shown["path"] == str((tmp_path / "stations" / "2sb.yaml").resolve())
        ended = json.loads(done.stdout.splitlines()[-1])["run"]
        noted = read_measurement(ended["path"]).metadata[PROFILE]
        assert noted["file"].startswith("stations/2sb@")
        assert (tmp_path / "experiment" / noted["file"]).exists()
    finally:
        thzdaq("daemon", "kill")
