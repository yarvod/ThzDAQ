import sys

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from PyQtAds import ads as QtAds

from store import restore_configs
from interface.index import App
from utils.dock import Dock


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


def get_dock_manager(main_app):
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.OpaqueSplitterResize, True)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.XmlCompressionEnabled, False)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.FocusHighlighting, True)
    return QtAds.CDockManager(main_app)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    init_settings()
    ex = App()
    dock_manager = get_dock_manager(ex)
    ex.dock_manager = dock_manager
    Dock.ex = ex
    ex.add_views()
    ex.create_perspective_ui()
    ex.restore_state()
    restore_configs()
    sys.exit(app.exec())
