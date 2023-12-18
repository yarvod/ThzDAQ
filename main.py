import sys

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

from api.Keithley import KeithleyPowerSupplyManager
from interface.index import App


def init_settings():
    settings_ini = QSettings("settings.ini", QSettings.IniFormat)
    settings = QSettings("ASC", "SIS manager")
    if "Perspectives" not in settings.childGroups():
        for key in settings_ini.allKeys():
            if "Perspectives" not in key:
                continue
            settings.setValue(key, settings_ini.value(key))
    if "Configs" not in settings.childGroups():
        for key in settings_ini.allKeys():
            if "Configs" not in key:
                continue
            settings.setValue(key, settings_ini.value(key))
    settings.sync()


def restore_configs():
    KeithleyPowerSupplyManager.restore_config()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    init_settings()
    ex = App()
    restore_configs()
    sys.exit(app.exec())
