"""ThzDAQ: the desktop application, and with --serve the bench daemon (entry point
for `uv run python main.py` and PyInstaller). The one place that knows both: a
built ThzDAQ.exe is the daemon its clients start."""

import sys

from thzdaq_api.host import SERVE, note_installation


def main() -> int:
    note_installation()
    arguments = sys.argv[1:]
    if SERVE in arguments:
        from thzdaq_daemon.__main__ import main as serve

        return serve([a for a in arguments if a != SERVE])
    from thzdaq_gui.app import main as gui

    return gui(arguments)


if __name__ == "__main__":
    sys.exit(main())
