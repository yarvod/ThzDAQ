"""thzdaq-cli.exe: the command line of a build, a console program next to the
windowed ThzDAQ.exe (entry point for PyInstaller; thzdaq from PyPI is the same
client)."""

import sys

from thzdaq_api.host import note_installation
from thzdaq_cli.app import main

if __name__ == "__main__":
    note_installation()
    sys.exit(main())
