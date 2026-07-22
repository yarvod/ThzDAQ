from PySide6.QtCore import Slot
from PySide6.QtWidgets import QComboBox


class DeviceComboBox(QComboBox):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        if self.manager.event_manager is not None:
            self.manager.event_manager.configs_updated.connect(self.refresh_configs)
        self.refresh_configs()

    @Slot()
    def refresh_configs(self):
        self.manager.update_combobox(self)

    def current_cid(self):
        return self.currentData()

    def current_config(self):
        cid = self.current_cid()
        if cid is None:
            return None
        return self.manager.get_config(cid)
