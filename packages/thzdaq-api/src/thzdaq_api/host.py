"""Where a client finds the daemon, and how it starts one when none runs.

A daemon writes its host file (port, token, versions) once it serves and
removes it when it ends; a lock the operating system holds keeps it the only
one. The simulator daemon is another daemon with its own files, so it runs
next to the real one. The files live in the temp folder, or in
THZDAQ_DAEMON_DIR (tests, a second bench on one machine).

A build runs its daemon as ThzDAQ.exe --serve, whichever of its programs
starts it; it notes itself in the install file of the user at each start, so
a client from PyPI without the daemon package starts that build's daemon.
"""

import ctypes
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
from typing import List, Optional, Sequence

import msgspec

from thzdaq_api.daemon import API_VERSION, HostInfo, Installation
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lock import FileLock
from thzdaq_api.remote import RemoteLab, health

logger = logging.getLogger(__name__)

DIR_ENV = "THZDAQ_DAEMON_DIR"
NO_AUTOSTART_ENV = "THZDAQ_NO_AUTOSTART"  # report "not running" instead of starting
START_S = 15.0  # how long a client waits for a daemon it started
LOG_KEEP = 5_000_000  # bytes of log kept before the next start moves it aside
SERVE = "--serve"  # how a built program runs as the daemon
PROGRAM = "ThzDAQ"  # the built program: the window, and the daemon with SERVE


@dataclass(frozen=True)
class DaemonFiles:
    """The files of one daemon: the real one, or the simulator's."""

    directory: Path
    name: str  # thzdaq, thzdaq-sim

    @classmethod
    def of(cls, simulate: bool = False) -> "DaemonFiles":
        directory = Path(os.environ.get(DIR_ENV) or tempfile.gettempdir())
        return cls(directory, "thzdaq-sim" if simulate else "thzdaq")

    @property
    def host(self) -> Path:
        return self.directory / f"{self.name}-host.json"

    @property
    def lock(self) -> Path:
        """Held by the living daemon: one per machine."""
        return self.directory / f"{self.name}-daemon.lock"

    @property
    def start_lock(self) -> Path:
        """Held while a client starts the daemon: two clients start one."""
        return self.directory / f"{self.name}-daemon-start.lock"

    @property
    def log(self) -> Path:
        return self.directory / f"{self.name}-daemon.log"


def frozen() -> bool:
    """A built program (PyInstaller), not a run from sources."""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """Folder of the program: next to the .exe when built, the working folder
    from sources. The working folder of a built program depends on how it was
    started (a shortcut, the updater), so files are never looked up relative
    to it."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def program_file() -> Path:
    """The built program of this installation (ThzDAQ.exe next to
    thzdaq-cli.exe; no suffix on macOS and Linux)."""
    return program_dir() / (PROGRAM + (".exe" if sys.platform == "win32" else ""))


def install_file() -> Path:
    """Where the build that started last notes itself, per user."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / PROGRAM / "install.json"


def note_installation() -> None:
    """A build notes itself at each start; from sources nothing is noted."""
    if not frozen():
        return
    path = install_file()
    noted = Installation(str(program_file()), app_version())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(msgspec.json.encode(noted))
        os.replace(partial, path)
    except OSError as e:  # the build works without it: only PyPI clients need it
        logger.warning(f"{path} not written: {e}")


def read_installation() -> Optional[Installation]:
    try:
        return msgspec.json.decode(install_file().read_bytes(), type=Installation)
    except (FileNotFoundError, msgspec.DecodeError, msgspec.ValidationError):
        return None


def app_version() -> str:
    try:
        return metadata.version("thzdaq-api")
    except metadata.PackageNotFoundError:  # a build without package metadata
        return "unknown"


def read_host(files: DaemonFiles) -> Optional[HostInfo]:
    """The host file, None when there is none (or it is not one)."""
    try:
        return msgspec.json.decode(files.host.read_bytes(), type=HostInfo)
    except FileNotFoundError:
        return None
    except (msgspec.DecodeError, msgspec.ValidationError):
        logger.warning(f"{files.host} is not a host file: ignored")
        return None


def write_host(files: DaemonFiles, host: HostInfo) -> None:
    """Atomically: a client never reads half of it."""
    files.directory.mkdir(parents=True, exist_ok=True)
    partial = files.host.with_suffix(".partial")
    partial.write_bytes(msgspec.json.encode(host))
    os.replace(partial, files.host)


def remove_host(files: DaemonFiles, pid: int) -> None:
    """The host file of this process goes; one another daemon wrote stays."""
    host = read_host(files)
    if host is not None and host.pid == pid:
        files.host.unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows
        synchronize, limited_query, still_active = 0x100000, 0x1000, 0x102
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(synchronize | limited_query, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == still_active
        finally:
            kernel.CloseHandle(handle)
    try:
        # A daemon this client started is its child: once it ends it stays a
        # zombie, which kill(pid, 0) still finds, until it is reaped here
        ended, _ = os.waitpid(pid, os.WNOHANG)
        return ended != pid
    except ChildProcessError:
        pass  # not a child of this process
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, another user's
    return True


def terminate(pid: int) -> None:
    """End a process at once (TerminateProcess, SIGKILL): a daemon that hangs."""
    os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)


def start_command() -> List[str]:
    """How the daemon starts: the built program of this installation with
    --serve; else this Python with the daemon package; else the build the
    install file names. LabError when there is none of them."""
    if frozen():
        return [str(program_file()), SERVE]
    if util.find_spec("thzdaq_daemon") is not None:
        return [sys.executable, "-m", "thzdaq_daemon"]
    installed = read_installation()
    if installed is not None and Path(installed.program).exists():
        return [installed.program, SERVE]
    raise LabError(
        ErrorCode.UNREACHABLE,
        "No daemon runs and none can be started here",
        "install thzdaq[daemon], or start the ThzDAQ build once",
    )


def spawn(command: Sequence[str], files: DaemonFiles) -> subprocess.Popen:
    """Start the daemon apart from this process (it outlives the client); its
    output goes to its log."""
    files.directory.mkdir(parents=True, exist_ok=True)
    if files.log.exists() and files.log.stat().st_size > LOG_KEEP:
        os.replace(files.log, files.log.with_suffix(".log.1"))
    if sys.platform == "win32":
        apart = dict(
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        apart = dict(start_new_session=True)
    with open(files.log, "ab") as log:
        return subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **apart,
        )


def log_tail(files: DaemonFiles, lines: int = 20) -> str:
    try:
        text = files.log.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def connect(
    simulate: bool = False, origin: str = "client", kind: str = "client"
) -> RemoteLab:
    """The running daemon; LabError UNREACHABLE when none answers, WRONG_VERSION
    when it speaks another contract."""
    files = DaemonFiles.of(simulate)
    host = read_host(files)
    if host is None:
        raise LabError(
            ErrorCode.UNREACHABLE,
            f"No {'simulator ' if simulate else ''}daemon runs",
            "connect_or_start() starts it",
        )
    answer = health(host)
    if answer is None:
        raise LabError(
            ErrorCode.UNREACHABLE,
            f"The daemon (pid {host.pid}, port {host.port}) does not answer",
            "it may hang: kill() ends it",
        )
    if answer.api_version != API_VERSION:
        raise LabError(
            ErrorCode.WRONG_VERSION,
            f"The daemon (pid {host.pid}, {answer.app_version}) speaks contract "
            f"{answer.api_version}, this client {API_VERSION}",
            "restart it with this installation when no measurement runs",
        )
    return RemoteLab(host, origin, kind, find=lambda: read_host(files))


def connect_or_start(
    simulate: bool = False,
    station: Optional[str] = None,
    origin: str = "client",
    kind: str = "client",
    command: Optional[Sequence[str]] = None,
    timeout: float = START_S,
) -> RemoteLab:
    """The running daemon, started first when none runs. Two clients starting
    at once start one daemon: the second finds the first one's."""
    try:
        return connect(simulate, origin, kind)
    except LabError as e:
        if e.code != ErrorCode.UNREACHABLE or os.environ.get(NO_AUTOSTART_ENV):
            raise
    files = DaemonFiles.of(simulate)
    starting = FileLock(files.start_lock)
    if not starting.acquire(timeout):
        raise LabError(
            ErrorCode.UNREACHABLE,
            "Another client is starting the daemon and it did not come up",
            log_tail(files),
        )
    try:
        try:
            return connect(simulate, origin, kind)  # another client started it
        except LabError as e:
            if e.code != ErrorCode.UNREACHABLE:
                raise
        host = read_host(files)
        if host is not None and pid_alive(host.pid):
            raise LabError(
                ErrorCode.UNREACHABLE,
                f"The daemon (pid {host.pid}) runs but does not answer",
                "kill() ends it",
            )
        files.host.unlink(missing_ok=True)  # left by a daemon that died
        arguments = list(command or start_command())
        if station:
            arguments += ["--station", str(station)]
        if simulate:
            arguments.append("--simulate")
        process = spawn(arguments, files)
        lab = _wait_for_start(files, process, simulate, origin, kind, timeout)
        logger.info(f"daemon started (pid {lab.host.pid})")
        return lab
    finally:
        starting.release()


def _wait_for_start(
    files: DaemonFiles,
    process: subprocess.Popen,
    simulate: bool,
    origin: str,
    kind: str,
    timeout: float,
) -> RemoteLab:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LabError(
                ErrorCode.UNREACHABLE,
                f"The daemon exited at start (code {process.returncode})",
                log_tail(files),
            )
        if read_host(files) is not None:
            try:
                return connect(simulate, origin, kind)
            except LabError as e:
                if e.code != ErrorCode.UNREACHABLE:
                    raise
        time.sleep(0.1)  # the daemon is another process: look again
    raise LabError(
        ErrorCode.UNREACHABLE,
        f"The daemon did not start in {timeout:g} s",
        log_tail(files),
    )


def kill(simulate: bool = False) -> Optional[int]:
    """End a daemon that does not answer; its pid, None when none ran.
    Measurement files it left running read as interrupted."""
    files = DaemonFiles.of(simulate)
    host = read_host(files)
    if host is None or not pid_alive(host.pid):
        files.host.unlink(missing_ok=True)
        return None
    terminate(host.pid)
    remove_host(files, host.pid)
    return host.pid
