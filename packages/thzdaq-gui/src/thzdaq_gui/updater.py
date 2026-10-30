"""Standalone updater (built as updater.exe): replaces the install folder with a new build.

Runs from a temporary copy after the application quits. Old files go to a
backup folder first and come back if anything fails. Bench profiles edited
in stations/ are kept; only profiles missing there are added. Windows does
not replace the files of a running program: what still runs from the
installation (another window, a daemon, thzdaq-cli.exe that an agent holds
for MCP) ends first, when the person agrees; otherwise the update waits.
Standard library only, so the frozen updater stays small.
"""

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

BACKUP = ".update_backup"
KEEP_EDITED = {"stations"}
LOG = "updater.log"

logger = logging.getLogger("thzdaq.updater")


# The updater starts once the application has decided to quit; what is left
# (stopping threads, a dump of the measurements) may still take a while
EXIT_TIMEOUT_S = 300.0
# A daemon the application stopped ends a moment later: waited for this long
STOPPING_S = 10.0


def wait_for_exit(pid: int, timeout: float = EXIT_TIMEOUT_S) -> bool:
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True  # already gone
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    return False


def processes() -> Iterator[Tuple[int, str]]:
    """Every process this user may look at, with the program it runs.
    On Linux ps names a program without its folder: none is found there."""
    if sys.platform == "win32":
        yield from _windows_processes()
        return
    listing = subprocess.run(
        ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=True
    ).stdout
    for line in listing.splitlines():
        pid, _, program = line.strip().partition(" ")
        yield int(pid), program.strip()


def _windows_processes() -> Iterator[Tuple[int, str]]:
    import ctypes
    from ctypes import wintypes

    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    size = 1024
    while True:
        pids = (wintypes.DWORD * size)()
        needed = wintypes.DWORD()
        psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed))
        if needed.value < ctypes.sizeof(pids):
            break
        size *= 2
    limited_query = 0x1000
    for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(limited_query, False, pid)
        if not handle:
            continue  # gone, or another user's
        try:
            length = wintypes.DWORD(32768)
            name = ctypes.create_unicode_buffer(length.value)
            if kernel32.QueryFullProcessImageNameW(
                handle, 0, name, ctypes.byref(length)
            ):
                yield pid, name.value
        finally:
            kernel32.CloseHandle(handle)


def running_from(folder: Path) -> List[Tuple[int, str]]:
    """Processes that run a program of the installation in folder."""
    folder = Path(folder).resolve()
    return [
        (pid, program)
        for pid, program in processes()
        if pid != os.getpid() and folder in Path(program).resolve().parents
    ]


def ask(question: str) -> bool:
    """Yes or no from the person; without a window to ask in, no."""
    logger.info(question)
    if sys.platform != "win32":
        return False
    import ctypes

    yes, yes_no_warning = 6, 0x04 | 0x30
    answer = ctypes.windll.user32.MessageBoxW(
        None, question, "ThzDAQ update", yes_no_warning
    )
    return answer == yes


def let_go(folder: Path, ask: Callable[[str], bool]) -> bool:
    """Nothing runs from folder any more: a daemon the application stopped
    ends by itself, the rest is ended when the person agrees. False: it runs."""
    deadline = time.monotonic() + STOPPING_S
    for pid, _ in running_from(folder):
        wait_for_exit(pid, max(0.0, deadline - time.monotonic()))
    running = running_from(folder)
    if not running:
        return True
    names = "\n".join(f"{Path(program).name} (pid {pid})" for pid, program in running)
    if not ask(
        f"These programs of ThzDAQ still run:\n\n{names}\n\nEnd them and install "
        "the update? An agent that uses thzdaq-cli.exe connects again later."
    ):
        return False
    for pid, program in running:
        logger.info("ending %s (pid %s)", program, pid)
        try:
            os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
        except OSError:
            pass  # it ended meanwhile
    return all(wait_for_exit(pid, STOPPING_S) for pid, _ in running)


def retry(action: Callable[[], None], attempts: int = 10, delay: float = 0.5) -> None:
    """Antivirus and the exiting process may hold files for a moment on Windows."""
    for attempt in range(attempts):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def add_missing(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if not (target / item.name).exists():
            copy(item, target / item.name)


def install(source: Path, target: Path) -> None:
    """Put the build from source into target; on failure target is restored."""
    source, target = Path(source), Path(target)
    backup = target / BACKUP
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir()
    moved: List[str] = []
    installed: List[str] = []
    keep_backup = False
    try:
        for item in sorted(source.iterdir()):
            name = item.name
            if name in KEEP_EDITED and (target / name).is_dir():
                add_missing(item, target / name)
                continue
            if (target / name).exists():
                retry(lambda: os.replace(target / name, backup / name))
                moved.append(name)
            installed.append(name)
            copy(item, target / name)
        logger.info("installed %s", ", ".join(installed))
    except Exception:
        logger.exception("install failed, restoring the previous version")
        for name in installed:
            try:
                remove(target / name)
            except OSError:
                logger.exception("could not remove %s", name)
        try:
            for name in moved:
                os.replace(backup / name, target / name)
        except OSError:
            keep_backup = True
            logger.exception("restore failed, the old files stay in %s", backup)
        raise
    finally:
        if not keep_backup:
            shutil.rmtree(backup, ignore_errors=True)


def show_error(message: str) -> None:
    logger.error(message)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ThzDAQ update", 0x10)


def setup_logging(target: Path) -> None:
    path = target / LOG
    try:
        open(path, "a").close()
    except OSError:
        path = Path(tempfile.gettempdir()) / f"thzdaq_{LOG}"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
    )


def cleanup(args) -> None:
    """The downloaded build is not needed after an attempt: free the disk."""
    folder = args.cleanup or args.source
    shutil.rmtree(folder, ignore_errors=True)
    logger.info("removed %s", folder)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="updater", description="ThzDAQ updater")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument(
        "--cleanup", type=Path, help="temporary download folder, removed at the end"
    )
    args = parser.parse_args(argv)

    setup_logging(args.target)
    logger.info("update %s <- %s", args.target, args.source)
    if not wait_for_exit(args.pid):
        cleanup(args)
        show_error(f"ThzDAQ (pid {args.pid}) did not quit, update cancelled.")
        return 1
    if not let_go(args.target, ask):
        cleanup(args)
        show_error(
            "Programs of ThzDAQ still run, update cancelled. Close them (an "
            "agent's thzdaq-cli.exe too) and install the update again."
        )
        return 1
    try:
        install(args.source, args.target)
    except Exception as e:
        cleanup(args)
        show_error(
            f"Update failed, the previous version is kept.\n\n{e}\n\n"
            f"Details: {args.target / LOG}"
        )
        code = 1
    else:
        cleanup(args)
        code = 0
    try:
        subprocess.Popen([str(args.exe)], cwd=str(args.target))
    except OSError as e:
        show_error(f"Could not start {args.exe}: {e}")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
