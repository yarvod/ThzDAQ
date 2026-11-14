"""Check the kernel of a console as the window starts it, without a display:
it starts, runs code, is interrupted, restarted and stopped. The kernel runs
with this Python from sources, or with a build's thzdaq-cli (the release
checks its build so). On Windows it starts without the standard output
handles of a terminal, as the windowed ThzDAQ.exe does:

    uv run python check_console.py [dist/ThzDAQ/thzdaq-cli.exe]
"""

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QCoreApplication
from thzdaq_api import console

from thzdaq_gui.kernel import Kernel

WAIT_S = 120.0  # a built kernel's first start on Windows is slow


class Failed(Exception):
    pass


def check(built: Optional[Path]) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    command = console.kernel_command(built=built)
    kernel = Kernel()
    told: List[tuple] = []
    for name in ("started", "failed", "died", "printed", "shown", "raised", "finished"):
        getattr(kernel, name).connect(lambda *a, n=name: told.append((n, *a)))

    def until(what: str, reached: Callable[[], bool]) -> None:
        deadline = time.monotonic() + WAIT_S
        while not reached():
            if time.monotonic() > deadline or any(t[0] == "failed" for t in told):
                raise Failed(f"{what}: {told[-3:]}")
            app.processEvents()
            time.sleep(0.01)
        print(f"ok: {what}")

    def finished(id: str) -> bool:
        return ("finished", id, "ok") in told or ("finished", id, "error") in told

    try:
        kernel.start(command, dict(os.environ), Path.cwd())
        until("started", lambda: ("started",) in told)
        id = kernel.execute("import thzdaq, numpy\n6 * 7")
        until("runs code", lambda: finished(id))
        if ("shown", id, "42") not in told:
            raise Failed(f"6 * 7 is not 42: {told[-3:]}")
        # IPython's Windows interrupt is delivered when Python executes again,
        # not while it is blocked in a native time.sleep.
        id = kernel.execute("print('running', flush=True)\nwhile True:\n    pass")
        until("runs long", lambda: ("printed", id, "stdout", "running\n") in told)
        kernel.interrupt()
        until("interrupted", lambda: ("finished", id, "error") in told)
        told.clear()
        kernel.restart(command, dict(os.environ), Path.cwd())
        until("restarted", lambda: ("started",) in told)
    finally:
        kernel.stop()
        if not kernel.join(30):
            raise Failed("not stopped")
    print("ok: stopped")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "cli", nargs="?", help="a build's thzdaq-cli (default: sources)"
    )
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        # Jupyter recognizes pythonw.exe, but not ThzDAQ.exe, as windowed.
        # Remove the OS handles so a terminal cannot hide broken inheritance.
        # Python's print still writes to this process's already open streams.
        from _winapi import STD_ERROR_HANDLE, STD_OUTPUT_HANDLE

        for handle in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            if not ctypes.windll.kernel32.SetStdHandle(handle, None):
                raise ctypes.WinError()
    try:
        check(Path(args.cli).resolve() if args.cli else None)
    except Failed as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
