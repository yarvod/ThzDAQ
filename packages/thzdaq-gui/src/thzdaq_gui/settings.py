"""Where the application keeps its state, and where its files live.

Settings (window layout, perspectives, last station profile, last parameters
of every measurement, I-V analysis) are in the registry on Windows
(HKEY_CURRENT_USER\\Software\\ThzDAQ\\<scope>; a plist on macOS, an INI file
on Linux), outside the program folder, so updates never touch them:

    ThzDAQ      the built application (PyInstaller)
    ThzDAQ-dev  runs from sources (uv run python main.py)

Files (measurements, dumps, station profiles) live next to the program and
the updater keeps them. --settings FILE uses an INI file instead (portable
setups, tests).
"""

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings
from thzdaq_api.host import frozen, program_dir
from thzdaq_api.measurements import DATA

ORGANIZATION = "ThzDAQ"
_file: Optional[str] = None


def scope() -> str:
    return "ThzDAQ" if frozen() else "ThzDAQ-dev"


def use_file(path) -> None:
    """Keep settings in this INI file instead of the registry (None: registry)."""
    global _file
    _file = None if path is None else str(path)


def settings() -> QSettings:
    if _file is not None:
        return QSettings(_file, QSettings.IniFormat)
    return QSettings(QSettings.NativeFormat, QSettings.UserScope, ORGANIZATION, scope())


def location() -> str:
    """Human readable place of the settings, e.g. the registry key."""
    if _file is not None:
        return _file
    if sys.platform == "win32":
        return f"HKEY_CURRENT_USER\\Software\\{ORGANIZATION}\\{scope()}"
    return settings().fileName()


# Every key of the settings, in one place; keys made of parts are functions
STATION_PATH = "station/path"  # the last station profile
WINDOW_GEOMETRY = "window/geometry"
MODE = "ui/mode"  # Lite or Pro
CHOSEN_MEASUREMENT = "ui/measurement"  # the one the Lite run bar shows
PRO_LAYOUT = "window/docks"  # also the layout saved before the modes
LITE_LAYOUT = "window/docks_lite"
PERSPECTIVES = "Perspectives"  # the array ADS writes and reads
PERSPECTIVE = "perspective"  # the one in use
CUSTOM_GRAPHS = "graphs/custom"
NAVIGATOR_EXPANDED = "navigator/expanded"
IV_ANALYSIS = "iv_analysis"
PRERELEASES = "updates/prereleases"
RECENT_WORKSPACES = "workspaces/recent"  # newest first
DEFAULT_WORKSPACE = "workspaces/default"  # opened at start; none: the program's
EDITOR = "workspaces/editor"  # the program a workspace opens in without VS Code


def procedure_key(procedure: str) -> str:
    """Last parameters and devices of a procedure's dock."""
    return f"procedures/{procedure}"


def sections_path(procedure: str, scan: bool = False) -> str:
    """Folded sections of a procedure: in its dock, or of its scan in a device dock."""
    return f"scan/{procedure}" if scan else procedure


# Folded or not in every device dock: what is rarely needed (raw commands)
ADVANCED = "device/advanced"


def section_key(path: str) -> str:
    return f"sections/{path}"


def unit_key(ref: str, quantity: str) -> str:
    """The SI prefix a field shows its value in."""
    return f"units/{ref}/{quantity}"


def setpoint_key(ref: str, key: str) -> str:
    """The last value set from a device dock."""
    return f"setpoints/{ref}/{key}"


def argument_key(ref: str, action: str, argument: str) -> str:
    """The last value of an action's argument given from a device dock."""
    return f"arguments/{ref}/{action}/{argument}"


def folder_key(kind: str) -> str:
    """The folder the file dialogs of a kind of file start in."""
    return f"folders/{kind}"


def app_dir() -> Path:
    return program_dir()


def data_dir() -> Path:
    """Where the program's own measurements go: the data of its folder."""
    return app_dir() / DATA


def stations_dir() -> Path:
    return app_dir() / "stations"
