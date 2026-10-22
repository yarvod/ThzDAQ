import sys

from PySide6.QtCore import QSettings
from thzdaq_gui import settings


def test_build_and_sources_use_separate_registry_scopes(monkeypatch):
    monkeypatch.setattr(settings, "_file", None)
    monkeypatch.delattr(sys, "frozen", raising=False)
    dev = settings.settings()
    assert settings.scope() == "ThzDAQ-dev"
    assert (dev.format(), dev.organizationName(), dev.applicationName()) == (
        QSettings.NativeFormat, "ThzDAQ", "ThzDAQ-dev",
    )  # fmt: skip
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/ThzDAQ/ThzDAQ")
    built = settings.settings()
    assert built.applicationName() == "ThzDAQ" and settings.scope() == "ThzDAQ"
    # Files of a build live next to it, whatever the working folder is
    assert settings.app_dir().as_posix().endswith("/opt/ThzDAQ")
    assert settings.data_dir() == settings.app_dir() / "data"
    assert settings.stations_dir() == settings.app_dir() / "stations"
    if sys.platform == "win32":
        assert settings.location() == r"HKEY_CURRENT_USER\Software\ThzDAQ\ThzDAQ"


def test_an_ini_file_replaces_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_file", None)
    settings.use_file(tmp_path / "portable.ini")
    values = settings.settings()
    values.setValue("station/path", "stations/lab.yaml")
    values.sync()
    assert values.format() == QSettings.IniFormat
    assert settings.location() == str(tmp_path / "portable.ini")
    assert "[station]\npath=stations/lab.yaml" in (tmp_path / "portable.ini").read_text()
