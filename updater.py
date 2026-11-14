"""Entry point of updater.exe, built next to ThzDAQ.exe by build.bat."""

import sys

from thzdaq_gui.updater import main

if __name__ == "__main__":
    sys.exit(main())
