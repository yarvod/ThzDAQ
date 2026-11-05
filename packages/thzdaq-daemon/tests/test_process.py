"""The daemon as a process: started by clients, one per machine, found again
after a restart, ended by a stop, an idle timeout or a kill."""

import json
import subprocess
import sys
import threading
import time

import msgspec
import pytest
from lab_helpers import bodies, wait_for
from thzdaq_api.data import encode_values
from thzdaq_api.daemon import (
    API_VERSION,
    GetDaemonStatus,
    Health,
    HostInfo,
    RestartDaemon,
    StopDaemon,
    StopMode,
)
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import MeasurementRecords, Resync
from thzdaq_api.host import (
    NO_AUTOSTART_ENV,
    DaemonFiles,
    connect,
    connect_or_start,
    kill,
    pid_alive,
    read_host,
    write_host,
)
from thzdaq_api.measurement_file import INTERRUPTED, read_measurement
from thzdaq_api.measurements import StartMeasurement
from thzdaq_api.procedures import MONITOR_TIME

FOREVER = {"watch": ["power_meter_1/power"], "interval": 0.05, "duration": 0.0}


def start(home, simulate=True, idle=60.0, origin="test"):
    command = [
        sys.executable, "-m", "thzdaq_daemon", "--home", str(home),
        "--idle-timeout", str(idle),
    ]  # fmt: skip
    station = str(home / "bench.yaml") if simulate else None
    return connect_or_start(simulate, station, origin, "test", command)


def gone(pid, files):
    wait_for(lambda: not pid_alive(pid) and read_host(files) is None, timeout=15)


def test_two_clients_at_once_start_one_daemon(home):
    labs = []
    threads = [threading.Thread(target=lambda: labs.append(start(home))) for _ in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({lab.host.pid for lab in labs}) == 1
    assert len(labs[0].call(ListDevices())) > 10
    log = DaemonFiles.of(True).log.read_text()
    assert log.count("Serving on port") == 1


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_a_stale_host_file_is_replaced(home):
    dead = dead_pid()
    write_host(
        DaemonFiles.of(True),
        HostInfo(dead, 1, "t", API_VERSION, "old", "", "", None, True),
    )
    lab = start(home)
    assert lab.host.pid != dead and pid_alive(lab.host.pid)


def test_without_autostart_a_missing_daemon_is_reported(home, monkeypatch):
    monkeypatch.setenv(NO_AUTOSTART_ENV, "1")
    with pytest.raises(LabError) as caught:
        start(home)
    assert caught.value.code == ErrorCode.UNREACHABLE
    assert read_host(DaemonFiles.of(True)) is None


def test_a_daemon_of_another_contract_is_not_used(home, served):
    served.server.health = Health(1, API_VERSION + 1, "future", True)
    # Its pid is one that ended: the cleanup kills no process of the tests
    write_host(
        DaemonFiles.of(True), msgspec.structs.replace(served.host, pid=dead_pid())
    )
    for attempt in (lambda: connect(True), lambda: start(home)):
        with pytest.raises(LabError) as caught:
            attempt()
        assert caught.value.code == ErrorCode.WRONG_VERSION


def test_the_simulator_runs_next_to_the_real_daemon(home):
    simulated, real = start(home), start(home, simulate=False)
    assert simulated.host.pid != real.host.pid
    assert simulated.call(GetDaemonStatus()).process.simulate
    assert not real.call(GetDaemonStatus()).process.simulate
    assert real.call(ListDevices()) == ()  # started without a profile


def test_idle_it_ends_and_a_listener_keeps_it(home):
    lab = start(home, idle=0.5)
    stop = lab.subscribe(lambda event: None)
    time.sleep(3.0)  # longer than the idle timeout and a heartbeat
    assert pid_alive(lab.host.pid)
    stop()
    gone(lab.host.pid, DaemonFiles.of(True))


def test_a_stop_waits_for_measurements_unless_it_cancels_them(home):
    lab = start(home)
    run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=FOREVER))
    with pytest.raises(LabError) as caught:
        lab.call(StopDaemon())
    assert caught.value.code == ErrorCode.CONFLICT
    lab.call(StopDaemon(mode=StopMode.CANCEL))
    gone(lab.host.pid, DaemonFiles.of(True))
    (saved,) = (home / "data").glob(f"*/{run.id:06d}_*.json")
    assert json.loads(saved.read_text())["status"] == "cancelled"


def test_after_a_restart_the_client_finds_the_new_daemon(home):
    lab = start(home)
    heard = []
    lab.subscribe(heard.append)
    old = lab.host.pid
    lab.call(RestartDaemon())
    wait_for(lambda: any(isinstance(e.body, Resync) for e in heard), timeout=20)
    assert lab.host.pid != old and not pid_alive(old)
    assert lab.call(GetDaemonStatus()).process.pid == lab.host.pid


def test_a_daemon_that_hangs_is_killed(home):
    lab = start(home)
    assert kill(True) == lab.host.pid
    gone(lab.host.pid, DaemonFiles.of(True))
    assert kill(True) is None


def test_a_killed_daemon_leaves_every_record_it_told_in_the_file(home):
    lab = start(home)
    heard = []
    stop = lab.subscribe(heard.append)
    run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=FOREVER))
    wait_for(lambda: len(bodies(heard, MeasurementRecords)) >= 10, timeout=15)
    stop()
    told = bodies(heard, MeasurementRecords)
    assert kill(True) == lab.host.pid
    gone(lab.host.pid, DaemonFiles.of(True))

    found = read_measurement(run.path)
    assert found.status == INTERRUPTED
    rows = [row for body in told for row in body.rows]
    kept = [encode_values(row) for row in found.records(told[0].table)]
    assert len(kept) >= len(rows) >= 10
    assert kept[: len(rows)] == rows


def test_a_windowed_build_says_what_it_says_into_its_log(tmp_path, monkeypatch):
    from thzdaq_daemon.__main__ import streams_to_log

    files = DaemonFiles(tmp_path / "files", "thzdaq")
    monkeypatch.setattr(sys, "stdout", None)  # ThzDAQ.exe --serve, started by hand
    monkeypatch.setattr(sys, "stderr", None)
    streams_to_log(files)
    print("serving")
    sys.stderr.write("a traceback\n")
    sys.stderr.close()
    assert files.log.read_text(encoding="utf-8") == "serving\na traceback\n"


def test_the_rights_of_agents_are_kept_for_the_next_start(tmp_path):
    """Changing them keeps the idle timeout it was started with to itself."""
    from thzdaq_api.daemon import DaemonSettings
    from thzdaq_api.operation import Rights
    from thzdaq_api.rights import Decision
    from thzdaq_daemon.process import IDLE_S, Daemon, Options

    files = DaemonFiles(tmp_path / "files", "thzdaq")
    started = Daemon(Options(tmp_path, files, simulate=True, idle_timeout=0.0))
    started.change(DaemonSettings(0.0, {Rights.SET: Decision.ALLOW}))
    assert started.idle_timeout == 0.0
    again = Daemon(Options(tmp_path, files, simulate=True))
    assert again.settings() == DaemonSettings(IDLE_S, {Rights.SET: Decision.ALLOW})
    assert '"set": "allow"' in (tmp_path / "daemon-sim.json").read_text()
