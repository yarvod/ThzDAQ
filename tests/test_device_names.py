import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

from interface.components.deviceComboBox import DeviceComboBox
from interface.components.deviceInfo import DeviceInfo
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store.deviceConfig import (
    DeviceConfig,
    DeviceConfigList,
    DeviceEventManager,
    DeviceManager,
)


class _NamedDeviceManager(DeviceManager):
    name = "Named Device"
    config_class = DeviceConfig
    configs = DeviceConfigList()
    main_widget_class = None


class _NamedDeviceSetup(SetUpDeviceWidget):
    widget_title = "Named devices"
    manager_class = _NamedDeviceManager


class _SetupWidgetStub:
    def create_device_info_widget(self, config, **kwargs):
        pass


class DeviceNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        _NamedDeviceManager.configs = DeviceConfigList()
        _NamedDeviceManager.last_id = 0
        _NamedDeviceManager.setup_widget = None
        _NamedDeviceManager.main_widget_class = None
        _NamedDeviceManager.event_manager = DeviceEventManager()
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def add_config(self, name=None):
        kwargs = {
            "adapter": "SOCKET",
            "host": "127.0.0.1",
            "port": "9876",
            "gpib": 0,
        }
        if name is not None:
            kwargs["name"] = name
        return _NamedDeviceManager.add_config(**kwargs)

    def test_add_form_is_immediately_filled_with_the_generated_name(self):
        setup = _NamedDeviceSetup(None)
        self.widgets.append(setup)

        setup.open_form_add_device()
        self.widgets.append(setup.form)

        self.assertEqual(setup.form.name.text(), "Named Device 1")
        setup.form.name.clear()
        self.assertEqual(
            setup.form.get_initialize_kwargs()["name"],
            "Named Device 1",
        )

    def test_custom_name_updates_config_label_and_device_selector(self):
        cid = self.add_config("Mixer A")
        config = _NamedDeviceManager.get_config(cid)
        combobox = DeviceComboBox(None, _NamedDeviceManager)
        info = DeviceInfo(
            None,
            config,
            adapter=config.adapter,
            host=config.host,
            port=config.port,
            gpib=config.gpib,
        )
        self.widgets.extend([combobox, info])

        info.edit()
        self.widgets.append(info.form)
        self.assertEqual(info.form.name.text(), "Mixer A")
        self.assertEqual(info.form.default_name, "Named Device 1")
        info.form.name.setText("Mixer B")

        with (
            patch.object(info, "initialize"),
            patch.object(_NamedDeviceManager, "persist_config") as persist_config,
        ):
            info.update_config_initialize(info.form.get_initialize_kwargs())

        self.assertEqual(config.name, "Mixer B")
        self.assertEqual(info.name.text(), "Mixer B")
        self.assertEqual(combobox.itemText(0), "Mixer B")
        self.assertEqual(config.dict()["name"], "Mixer B")
        self.assertNotIn("_name", config.dict())
        persist_config.assert_called_once_with()

    def test_blank_manager_name_falls_back_to_the_generated_name(self):
        cid = self.add_config("   ")

        self.assertEqual(
            _NamedDeviceManager.get_config(cid).name,
            "Named Device 1",
        )

    def test_dock_identity_stays_stable_when_display_name_changes(self):
        _NamedDeviceManager.main_widget_class = "fake.DeviceWidget"
        widget_class = object()
        with (
            patch("store.deviceConfig.import_class", return_value=widget_class),
            patch("store.deviceConfig.Dock.add_widget_to_dock") as add_to_dock,
        ):
            cid = self.add_config("Mixer A")

        add_to_dock.assert_called_once_with(
            name="Named Device 1",
            title="Mixer A",
            widget_class=widget_class,
            cid=cid,
            menu="device",
        )

        with patch("store.deviceConfig.Dock.rename_widget_in_dock") as rename_dock:
            _NamedDeviceManager.rename_config(cid, "Mixer B", persist=False)
        rename_dock.assert_called_once_with("Named Device 1", "Mixer B")

        with patch("store.deviceConfig.Dock.delete_widget_from_dock") as delete_dock:
            _NamedDeviceManager.delete_config(cid, persist=False)
        delete_dock.assert_called_once_with(name="Named Device 1")

    def test_custom_names_persist_and_legacy_names_are_migrated(self):
        self.add_config("Cryostat mixer")
        _NamedDeviceManager.setup_widget = _SetupWidgetStub()

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = QSettings(
                str(Path(temp_dir) / "settings.ini"),
                QSettings.IniFormat,
            )
            _NamedDeviceManager.store_config(settings)
            stored = settings.value(f"Configs/{_NamedDeviceManager.name}")
            self.assertEqual(stored[0]["name"], "Cryostat mixer")
            self.assertNotIn("_name", stored[0])

            _NamedDeviceManager.configs = DeviceConfigList()
            _NamedDeviceManager.last_id = 0
            _NamedDeviceManager.restore_config(settings)
            self.assertEqual(
                _NamedDeviceManager.get_config(1).name,
                "Cryostat mixer",
            )

            settings.setValue(
                f"Configs/{_NamedDeviceManager.name}",
                [
                    {
                        "_name": _NamedDeviceManager.name,
                        "cid": 7,
                        "adapter": "SOCKET",
                        "host": "127.0.0.2",
                        "port": "9876",
                        "gpib": 0,
                    }
                ],
            )
            settings.sync()
            _NamedDeviceManager.configs = DeviceConfigList()
            _NamedDeviceManager.last_id = 0
            _NamedDeviceManager.restore_config(settings)
            self.assertEqual(
                _NamedDeviceManager.get_config(1).name,
                "Named Device 1",
            )


if __name__ == "__main__":
    unittest.main()
