"""Per-user preferences (last parameters, analysis settings) in an INI file.

The layout and perspectives live in settings.ini next to the application;
these are personal and go to the user's config folder. Tests redirect it
with QSettings.setPath().
"""

from PySide6.QtCore import QSettings


def prefs() -> QSettings:
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "ThzDAQ", "thzdaq-gui")
