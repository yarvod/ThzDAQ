import sys

from PySide6.QtWidgets import QApplication
import PySide6QtAds as QtAds

from store import restore_configs
from interface.index import App
from utils.dock import Dock
from utils.logger import configure_logger


def get_dock_manager(main_app):
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.OpaqueSplitterResize, False)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.XmlCompressionEnabled, True)
    QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.FocusHighlighting, True)
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.DefaultAutoHideConfig)
    return QtAds.CDockManager(main_app)


if __name__ == "__main__":
    configure_logger()
    app = QApplication(sys.argv)
    ex = App()
    dock_manager = get_dock_manager(ex)
    ex.dock_manager = dock_manager
    Dock.ex = ex
    ex.add_views()
    ex.create_perspective_ui()
    ex.init_settings()
    restore_configs(ex.settings)
    ex.restore_state()
    sys.exit(app.exec())
