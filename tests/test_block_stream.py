from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from interface.views.blockTabWidget import BlockStreamThread
from store import ScontelSisBlockManager
from store.base import MeasureType


class BlockStreamThreadTest(TestCase):
    def test_stores_aligned_samples_and_keeps_zero_values(self):
        config = SimpleNamespace(thread_stream=False, dict=lambda: {})
        block = Mock()
        block.get_bias_voltage.return_value = 0.0
        block.get_bias_current.return_value = None

        def get_ctrl_current():
            config.thread_stream = False
            return 0.0

        block.get_ctrl_current.side_effect = get_ctrl_current

        with (
            patch.object(
                ScontelSisBlockManager,
                "get_config",
                return_value=config,
            ),
            patch(
                "interface.views.blockTabWidget.SisBlock",
                return_value=block,
            ),
        ):
            thread = BlockStreamThread(
                cid=3,
                polling_interval=0,
                store_data=True,
            )
            thread.run()

        self.assertEqual(thread.measure.measure_type, MeasureType.SIS_BLOCK_STREAM)
        self.assertEqual(thread.measure.data["block_cid"], 3)
        self.assertEqual(thread.measure.data["polling_interval_s"], 0)
        self.assertEqual(len(thread.measure.data["time_s"]), 1)
        self.assertEqual(thread.measure.data["bias_voltage_mV"], [0.0])
        self.assertEqual(thread.measure.data["bias_current_uA"], [None])
        self.assertEqual(thread.measure.data["ctrl_current_mA"], [0.0])
        self.assertNotEqual(thread.measure.finished, "--")
        block.disconnect.assert_called_once_with()
