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

ORGANIZATION = "ThzDAQ"
_file: Optional[str] = None


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


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


def app_dir() -> Path:
    """Folder of the program: next to the .exe when built, the working folder from sources.

    The working folder of a built program depends on how it was started (a
    shortcut, the updater), so files are never looked up relative to it.
    """
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def data_dir() -> Path:
    return app_dir() / "data"


def stations_dir() -> Path:
    return app_dir() / "stations"
