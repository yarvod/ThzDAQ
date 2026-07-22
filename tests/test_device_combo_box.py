import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from interface.components.deviceComboBox import DeviceComboBox
from store.deviceConfig import (
    DeviceConfig,
    DeviceConfigList,
    DeviceEventManager,
    DeviceManager,
)


class _ComboManager(DeviceManager):
    name = "Test device"
    config_class = DeviceConfig
    configs = DeviceConfigList()
    event_manager = DeviceEventManager()
    main_widget_class = None


class DeviceComboBoxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        _ComboManager.configs = DeviceConfigList()
        _ComboManager.last_id = 0

    def add_config(self, host: str) -> int:
        return _ComboManager.add_config(
            adapter="SOCKET",
            host=host,
            port="9876",
            gpib=0,
        )

    def combo_state(self, combobox):
        return [
            (combobox.itemText(index), combobox.itemData(index))
            for index in range(combobox.count())
        ]

    def test_refresh_tracks_add_delete_without_duplicates(self):
        first_cid = self.add_config("127.0.0.1")
        second_cid = self.add_config("127.0.0.2")
        combobox = DeviceComboBox(None, _ComboManager)

        self.assertEqual(
            self.combo_state(combobox),
            [
                ("Test device 1", first_cid),
                ("Test device 2", second_cid),
            ],
        )

        combobox.setCurrentIndex(combobox.findData(second_cid))
        third_cid = self.add_config("127.0.0.3")
        self.assertEqual(combobox.current_cid(), second_cid)
        self.assertEqual(
            self.combo_state(combobox),
            [
                ("Test device 1", first_cid),
                ("Test device 2", second_cid),
                ("Test device 3", third_cid),
            ],
        )

        with patch("store.deviceConfig.Dock.delete_widget_from_dock"), patch.object(
            _ComboManager, "persist_config", return_value=True
        ) as persist_config:
            _ComboManager.delete_config(first_cid)
        persist_config.assert_called_once_with()
        self.assertEqual(combobox.current_cid(), second_cid)
        self.assertEqual(
            self.combo_state(combobox),
            [
                ("Test device 2", second_cid),
                ("Test device 3", third_cid),
            ],
        )

        with patch("store.deviceConfig.Dock.delete_widget_from_dock"):
            _ComboManager.delete_config(second_cid, persist=False)
        self.assertEqual(combobox.current_cid(), third_cid)
        self.assertEqual(
            self.combo_state(combobox),
            [("Test device 3", third_cid)],
        )

        combobox.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        # The manager signal must not retain or call an already deleted widget.
        self.add_config("127.0.0.4")


if __name__ == "__main__":
    unittest.main()
