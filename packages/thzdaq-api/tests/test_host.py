"""The client's side of the daemon: its files, the frames of its event stream."""

import os
import subprocess
import sys
from pathlib import Path

import msgspec
import pytest
from thzdaq_api import host
from thzdaq_api.daemon import API_VERSION, HostInfo, Installation
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.host import (
    SERVE,
    DaemonFiles,
    note_installation,
    pid_alive,
    program_file,
    read_host,
    remove_host,
    start_command,
    write_host,
)
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


def test_a_build_starts_its_own_daemon_whichever_program_starts_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "thzdaq-cli.exe"))
    program = Path(start_command()[0])
    assert start_command() == [str(program_file()), SERVE]
    assert program.parent == tmp_path and program.stem == "ThzDAQ"


def test_a_client_without_the_daemon_starts_the_build_that_started_last(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        host, "install_file", lambda: tmp_path / "user" / "install.json"
    )
    monkeypatch.setattr(host.util, "find_spec", lambda name: None)  # thzdaq from PyPI
    with pytest.raises(LabError) as caught:
        start_command()
    assert caught.value.code == ErrorCode.UNREACHABLE
    assert "thzdaq[daemon]" in caught.value.hint
    monkeypatch.setattr(sys, "executable", str(tmp_path / "build" / "ThzDAQ.exe"))
    note_installation()  # from sources: nothing is noted
    assert not host.install_file().exists()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    program = program_file()
    program.parent.mkdir()
    program.write_bytes(b"")
    note_installation()  # the build at its start
    monkeypatch.delattr(sys, "frozen")
    assert start_command() == [str(program), SERVE]
    program.unlink()  # the build was deleted since
    with pytest.raises(LabError):
        start_command()


def test_the_window_and_the_command_line_start_as_installed(tmp_path, monkeypatch):
    # From sources and PyPI: their packages in this Python
    assert host.window_command() == [sys.executable, "-m", "thzdaq_gui"]
    assert host.cli_command() == [sys.executable, "-m", "thzdaq_cli"]
    # A build: its programs, next to each other
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "thzdaq-cli.exe"))
    assert host.window_command() == [str(program_file())]
    (cli,) = host.cli_command()
    assert Path(cli).parent == tmp_path and Path(cli).stem == "thzdaq-cli"


def test_a_client_without_the_window_opens_the_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "install_file", lambda: tmp_path / "install.json")
    monkeypatch.setattr(host.util, "find_spec", lambda name: None)
    with pytest.raises(LabError) as caught:
        host.window_command()
    assert "thzdaq[gui]" in caught.value.hint
    program = host.executable(tmp_path / "build", "ThzDAQ")
    program.parent.mkdir()
    program.write_bytes(b"")
    host.install_file().write_bytes(
        msgspec.json.encode(Installation(str(program), "1.0"))
    )
    assert host.window_command() == [str(program)]
    assert host.cli_command() == [str(host.executable(program.parent, "thzdaq-cli"))]
