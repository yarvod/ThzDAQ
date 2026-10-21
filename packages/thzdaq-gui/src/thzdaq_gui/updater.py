"""Standalone updater (built as updater.exe): replaces the install folder with a new build.

Runs from a temporary copy after the application quits. Old files go to a
backup folder first and come back if anything fails. Bench profiles edited
in stations/ are kept; only profiles missing there are added.
Standard library only, so the frozen updater stays small.
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

BACKUP = ".update_backup"
KEEP_EDITED = {"stations"}
LOG = "updater.log"

logger = logging.getLogger("thzdaq.updater")


def wait_for_exit(pid: int, timeout: float = 60.0) -> bool:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="updater", description="ThzDAQ updater")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args(argv)

    setup_logging(args.target)
    logger.info("update %s <- %s", args.target, args.source)
    if not wait_for_exit(args.pid):
        show_error(f"ThzDAQ (pid {args.pid}) did not quit, update cancelled.")
        return 1
    try:
        install(args.source, args.target)
    except Exception as e:
        show_error(
            f"Update failed, the previous version is kept.\n\n{e}\n\n"
            f"Details: {args.target / LOG}"
        )
        code = 1
    else:
        shutil.rmtree(args.source, ignore_errors=True)
        code = 0
    try:
        subprocess.Popen([str(args.exe)], cwd=str(args.target))
    except OSError as e:
        show_error(f"Could not start {args.exe}: {e}")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
