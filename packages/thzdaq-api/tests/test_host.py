"""The client's side of the daemon: its files, the frames of its event stream."""

import os
import subprocess
import sys

from thzdaq_api.daemon import API_VERSION, HostInfo
from thzdaq_api.host import DaemonFiles, pid_alive, read_host, remove_host, write_host
from thzdaq_api.lock import FileLock
from thzdaq_api.transport import frame, frames


def test_the_real_and_the_simulator_daemon_have_their_own_files(tmp_path, monkeypatch):
    monkeypatch.setenv("THZDAQ_DAEMON_DIR", str(tmp_path))
    real, simulated = DaemonFiles.of(False), DaemonFiles.of(True)
    assert real.directory == tmp_path
    assert {real.host, real.lock, real.log}.isdisjoint(
        {simulated.host, simulated.lock, simulated.log}
    )


def test_a_host_file_is_read_as_written_and_only_its_owner_removes_it(tmp_path):
    files = DaemonFiles(tmp_path, "thzdaq")
    host = HostInfo(41, 5000, "t", API_VERSION, "1.0", "py", "now", None, False)
    assert read_host(files) is None
    write_host(files, host)
    assert read_host(files) == host
    remove_host(files, pid=42)  # another daemon's: stays
    assert read_host(files) == host
    files.host.write_text("{half")
    assert read_host(files) is None  # not a host file: as good as none
    remove_host(files, pid=41)
    assert files.host.exists()  # unreadable, so not known to be its own


def test_a_lock_is_held_by_one(tmp_path):
    first, second = FileLock(tmp_path / "x.lock"), FileLock(tmp_path / "x.lock")
    assert first.acquire()
    other = subprocess.run(
        [sys.executable, "-c", "import sys; from thzdaq_api.lock import FileLock; "
         f"sys.exit(0 if FileLock({str(tmp_path / 'x.lock')!r}).acquire() else 3)"],
    )  # fmt: skip
    assert other.returncode == 3
    first.release()
    assert second.acquire() and second.held


def test_a_process_is_alive_until_it_ends():
    assert pid_alive(os.getpid())
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    assert not pid_alive(process.pid)


def test_frames_of_the_event_stream():
    stream = b": ping\n\n" + frame("values", b'{"a": 1}', 7) + frame("heartbeat", b"{}")
    found = list(frames(iter(stream.splitlines(keepends=True))))
    assert [(f.event, f.data, f.id) for f in found] == [
        ("values", '{"a": 1}', "7"),
        ("heartbeat", "{}", None),
    ]
