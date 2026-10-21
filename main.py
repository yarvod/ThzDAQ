"""ThzDAQ desktop application (entry point for `uv run python main.py` and PyInstaller)."""

import sys

from thzdaq_gui.app import main

if __name__ == "__main__":
    sys.exit(main())
