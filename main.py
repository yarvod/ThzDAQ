import sys

from PyQt5.QtWidgets import QApplication
import PyQtAds as QtAds

from store import restore_configs
from interface.index import App
from utils.dock import Dock


def get_dock_manager(main_app):
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.OpaqueSplitterResize, True)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.XmlCompressionEnabled, False)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.FocusHighlighting, True)
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.DefaultAutoHideConfig)
    return QtAds.CDockManager(main_app)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = App()
    dock_manager = get_dock_manager(ex)
    ex.dock_manager = dock_manager
    Dock.ex = ex
    ex.add_views()
    ex.create_perspective_ui()
    # ex.init_settings()
    ex.restore_state()
    restore_configs(ex.settings)
    sys.exit(app.exec())
