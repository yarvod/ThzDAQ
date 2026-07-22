import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from interface.views.blockTabWidget import BlockCalibrateThread
from store import ScontelSisBlockManager
from store.deviceConfig import DeviceConfigList
from store.sisCalibration import (
    CALIBRATION_FIELDS,
    default_sis_calibration,
    normalize_sis_calibration,
)


class _SetupWidgetStub:
    def create_device_info_widget(self, config, **kwargs):
        pass


class _AdapterStub:
    def __init__(self):
        self.queries = []

    def query(self, command):
        self.queries.append(command)


class _SisBlockStub:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.adapter = _AdapterStub()
        self.disconnected = False
        self.instances.append(self)

    def disconnect(self):
        self.disconnected = True


class SisCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.manager_state = {
            "configs": ScontelSisBlockManager.configs,
            "last_id": ScontelSisBlockManager.last_id,
            "main_widget_class": ScontelSisBlockManager.main_widget_class,
            "setup_widget": ScontelSisBlockManager.setup_widget,
        }
        ScontelSisBlockManager.configs = DeviceConfigList()
        ScontelSisBlockManager.last_id = 0
        ScontelSisBlockManager.main_widget_class = None
        ScontelSisBlockManager.setup_widget = _SetupWidgetStub()

    def tearDown(self):
        for name, value in self.manager_state.items():
            setattr(ScontelSisBlockManager, name, value)

    def test_default_coefficients_are_independent(self):
        first = default_sis_calibration("DEV4")
        second = default_sis_calibration("DEV4")

        first["VoltageAdc"][0] = 123

        self.assertNotEqual(first, second)
        self.assertNotEqual(first["VoltageAdc"][0], second["VoltageAdc"][0])

    def test_validation_requires_the_full_schema(self):
        calibration = default_sis_calibration("DEV2")
        normalized = normalize_sis_calibration(calibration)

        self.assertEqual(set(normalized), set(CALIBRATION_FIELDS))

        invalid = deepcopy(calibration)
        invalid.pop("CurrentADC")
        with self.assertRaisesRegex(ValueError, "Missing calibration fields"):
            normalize_sis_calibration(invalid)

    def test_coefficients_are_saved_for_each_block(self):
        first_cid = ScontelSisBlockManager.add_config(
            adapter="SOCKET",
            host="127.0.0.1",
            port="9876",
            bias_dev="DEV4",
            ctrl_dev="DEV3",
        )
        second_cid = ScontelSisBlockManager.add_config(
            adapter="SOCKET",
            host="127.0.0.2",
            port="9876",
            bias_dev="DEV2",
            ctrl_dev="DEV1",
        )
        first_calibration = default_sis_calibration("DEV4")
        first_calibration["VoltageAdc"][1] = -0.123

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = QSettings(
                str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat
            )
            ScontelSisBlockManager.save_calibration_coefficients(
                first_cid, first_calibration, settings
            )
            stored_configs = settings.value(f"Configs/{ScontelSisBlockManager.name}")

        self.assertEqual(
            stored_configs[0]["calibration_coefficients"]["VoltageAdc"][1],
            -0.123,
        )
        self.assertNotEqual(
            stored_configs[0]["calibration_coefficients"],
            stored_configs[1]["calibration_coefficients"],
        )
        self.assertEqual(
            ScontelSisBlockManager.get_config(second_cid).bias_dev,
            "DEV2",
        )

    def test_missing_coefficients_are_initialized_with_device_defaults(self):
        configs_without_coefficients = [
            {
                "_name": ScontelSisBlockManager.name,
                "cid": 1,
                "adapter": "SOCKET",
                "host": "127.0.0.1",
                "port": "9876",
                "gpib": 0,
                "bias_dev": "DEV4",
                "ctrl_dev": "DEV3",
                "offset_voltage": 0.0,
                "offset_current": 0.0,
            },
            {
                "_name": ScontelSisBlockManager.name,
                "cid": 2,
                "adapter": "SOCKET",
                "host": "127.0.0.2",
                "port": "9876",
                "gpib": 0,
                "bias_dev": "DEV2",
                "ctrl_dev": "DEV1",
                "offset_voltage": 0.0,
                "offset_current": 0.0,
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = QSettings(
                str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat
            )
            settings.setValue(
                f"Configs/{ScontelSisBlockManager.name}",
                configs_without_coefficients,
            )
            settings.sync()

            ScontelSisBlockManager.restore_config(settings)
            stored_configs = settings.value(f"Configs/{ScontelSisBlockManager.name}")

        first, second = ScontelSisBlockManager.configs
        self.assertEqual(
            first.calibration_coefficients, default_sis_calibration("DEV4")
        )
        self.assertEqual(
            second.calibration_coefficients, default_sis_calibration("DEV2")
        )
        self.assertIn("calibration_coefficients", stored_configs[0])
        self.assertIsNot(
            first.calibration_coefficients, second.calibration_coefficients
        )

    def test_calibration_writes_selected_blocks_full_json(self):
        cid = ScontelSisBlockManager.add_config(
            adapter="SOCKET",
            host="127.0.0.1",
            port="9876",
            bias_dev="DEV2",
            ctrl_dev="DEV1",
        )
        calibration = default_sis_calibration("DEV2")
        calibration["CurrentMonitorResistance"] = 42
        ScontelSisBlockManager.get_config(cid).calibration_coefficients = calibration
        _SisBlockStub.instances = []

        with patch("interface.views.blockTabWidget.SisBlock", _SisBlockStub):
            BlockCalibrateThread(None, cid).run()

        block = _SisBlockStub.instances[0]
        command, payload = block.adapter.queries[0].split(" ", 1)
        self.assertEqual(command, "BIAS:DEV2:EEPR")
        self.assertEqual(json.loads(payload), calibration)
        self.assertTrue(block.disconnected)


if __name__ == "__main__":
    unittest.main()
