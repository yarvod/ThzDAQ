from unittest import TestCase
from unittest.mock import Mock

import numpy as np
from alvar import db_to_absolute

from interface.views.measures.two_sb.devices import IfSwitch
from interface.views.measures.two_sb.params import (
    DETECTOR_YIG,
    IF_SWITCH_RIGOL,
    IF_SWITCH_RS,
    SOURCE_RF,
    HotColdParams,
    IfBalanceParams,
    IfSweep,
    OptimizationParams,
    PumpBalanceParams,
    SrrParams,
    TnParams,
    TwoSbSetup,
)
from interface.views.measures.two_sb.threads import (
    IfBalanceThread,
    OptimizationThread,
    PumpBalanceThread,
    SrrThread,
    TnThread,
)
from store.base import MeasureType
from utils.functions import calc_m_dsb, calc_r1, calc_r2, get_if_tn, to_db_10
from utils.two_sb import (
    bias_grid,
    noise_temperature,
    parse_float_list,
    power_difference,
    sideband_rejection,
    split_chunks,
    sweep,
    test_tone_frequency,
)

HOT_COLD = HotColdParams(chopper_delay=0)


class TwoSbHelpersTest(TestCase):
    def test_parse_float_list(self):
        self.assertEqual(parse_float_list(" 5, 6;7  8.5 "), [5.0, 6.0, 7.0, 8.5])
        self.assertEqual(parse_float_list(""), [])
        with self.assertRaises(ValueError):
            parse_float_list("5, x")

    def test_bias_grid_is_full_product(self):
        self.assertEqual(bias_grid([5, 6], [5, 6]), [(5, 5), (5, 6), (6, 5), (6, 6)])

    def test_sweep_includes_stop(self):
        np.testing.assert_allclose(sweep(2.1, 2.6, 0.1), [2.1, 2.2, 2.3, 2.4, 2.5, 2.6])
        np.testing.assert_allclose(sweep(1, 1, 0.1), [1])
        with self.assertRaises(ValueError):
            sweep(1, 2, 0)

    def test_split_chunks_keeps_tail(self):
        chunks = split_chunks(np.arange(25), 10)
        self.assertEqual([len(c) for c in chunks], [10, 10, 5])

    def test_power_difference_is_wanted_minus_image(self):
        np.testing.assert_allclose(power_difference([-20], [-40], "upper"), [20])
        np.testing.assert_allclose(power_difference([-40], [-20], "lower"), [20])

    def test_test_tone_frequency(self):
        self.assertEqual(test_tone_frequency(223e9, 5e9, "upper"), 228e9)
        self.assertEqual(test_tone_frequency(223e9, 5e9, "lower"), 218e9)

    def test_noise_temperature_matches_existing_helper(self):
        self.assertAlmostEqual(
            float(noise_temperature(-30, -32)), float(get_if_tn(-30, -32))
        )

    def test_sideband_rejection_matches_script_formula(self):
        p = dict(
            p_upper_hot=-30.0,
            p_upper_cold=-32.0,
            p_lower_hot=-30.5,
            p_lower_cold=-32.7,
            usb_power_upper=-20.0,
            usb_power_lower=-35.0,
            lsb_power_upper=-37.0,
            lsb_power_lower=-21.0,
        )
        # Same math as measures/2sb_optimize.py calc_srr
        m_dsb = calc_m_dsb(
            db_to_absolute(p["p_upper_hot"]),
            db_to_absolute(p["p_upper_cold"]),
            db_to_absolute(p["p_lower_hot"]),
            db_to_absolute(p["p_lower_cold"]),
        )
        mu = db_to_absolute(p["usb_power_upper"]) / db_to_absolute(p["usb_power_lower"])
        ml = db_to_absolute(p["lsb_power_lower"]) / db_to_absolute(p["lsb_power_upper"])
        expected = (
            float(to_db_10(calc_r1(mu, ml, m_dsb))),
            float(to_db_10(calc_r2(mu, ml, m_dsb))),
        )
        np.testing.assert_allclose(sideband_rejection(**p), expected)


class IfSwitchTest(TestCase):
    def test_rigol_routes_upper_to_output_on(self):
        supply = Mock()
        switch = IfSwitch(supply, IF_SWITCH_RIGOL, channel=2, yig_power_channel=3)
        switch.select("upper")
        switch.select("lower")
        switch.set_yig_power(True)
        self.assertEqual(
            [c.args for c in supply.set_output.call_args_list],
            [(2, True), (2, False), (3, True)],
        )

    def test_rs_inverted_and_yig_not_controlled(self):
        supply = Mock()
        switch = IfSwitch(supply, IF_SWITCH_RS, channel=1, upper_when_on=False)
        switch.select("upper")
        switch.set_yig_power(True)
        supply.set_output_state.assert_called_once_with(1, False)


class FakeDevices:
    """Mixer model: test tone leaks 20 dB into the image channel, hot load +2 dB."""

    LO = 223e9

    def __init__(self, setup: TwoSbSetup):
        self.setup = setup
        self.sis1 = self._sis(2.5e-3, 10e-6)
        self.sis2 = self._sis(2.4e-3, 12e-6)
        self.lo = Mock()
        self.test_tone = Mock()
        self.test_tone.set_rf_output_state.side_effect = self._set_tone
        self.chopper = Mock()
        self.chopper.align_to_hot.side_effect = lambda: setattr(self, "load", "hot")
        self.chopper.align_to_cold.side_effect = lambda: setattr(self, "load", "cold")
        self.if_switch = Mock()
        self.if_switch.select.side_effect = lambda sb: setattr(self, "channel", sb)
        self.load = "cold"
        self.channel = "upper"
        self.tone_on = False
        self.tone_frequency = None
        self.yig_frequencies = []
        self.closed = False

    @staticmethod
    def _sis(voltage, current):
        sis = Mock()
        sis.get_bias_voltage.return_value = voltage
        sis.get_bias_current.return_value = current
        return sis

    def _set_tone(self, value):
        self.tone_on = value

    def set_lo_frequency(self, frequency):
        self.lo_frequency = frequency

    def set_test_tone_frequency(self, frequency):
        self.tone_frequency = frequency

    def set_yig_frequency(self, frequency):
        self.yig_frequencies.append(frequency)

    def read_power(self):
        if self.tone_on:
            tone = "upper" if self.tone_frequency > self.LO else "lower"
            return -20.0 if tone == self.channel else -40.0
        return -30.0 if self.load == "hot" else -32.0

    def close(self):
        self.closed = True


def run_thread(thread_class, params, setup=None):
    setup = setup or TwoSbSetup(sis1_cid=1, sis2_cid=2, if_switch_cid=1)
    devices = FakeDevices(setup)
    thread = thread_class(setup=setup, params=params, devices=devices)
    plots, errors = [], []
    thread.plot.connect(lambda dock, payload: plots.append((dock, payload)))
    thread.error.connect(errors.append)
    thread.run()
    return thread, devices, plots, errors


class TwoSbThreadsTest(TestCase):
    def test_tn_measures_both_channels_and_restores_state(self):
        params = TnParams(
            lo_frequency=223,
            precise_bias=False,
            if_sweep=IfSweep(4, 5, 3),
            switch_delay=0,
            point_delay=0,
            hot_cold=HOT_COLD,
        )
        thread, devices, plots, errors = run_thread(TnThread, params)

        self.assertEqual(errors, [])
        data = thread.measure.data
        self.assertEqual(thread.measure.measure_type, MeasureType.TWO_SB_TN)
        self.assertEqual(devices.lo_frequency, 223e9)
        for side_band in ("upper", "lower"):
            self.assertEqual(data[f"p_{side_band}_hot"], [-30.0] * 3)
            np.testing.assert_allclose(data[f"y_factor_{side_band}"], [2.0] * 3)
            np.testing.assert_allclose(
                data[f"tn_{side_band}"], [float(get_if_tn(-30, -32))] * 3
            )
        self.assertEqual(devices.load, "cold")
        devices.sis1.set_bias_voltage.assert_any_call(2.5e-3)
        self.assertEqual(devices.sis1.set_bias_voltage.call_args.args, (2.5e-3,))
        self.assertTrue(devices.closed)
        self.assertNotEqual(thread.measure.finished, "--")
        self.assertIn("Tn-IF curve", {dock for dock, _ in plots})

    def test_srr_with_yig_and_y_factor(self):
        params = SrrParams(
            lo_frequency=223,
            precise_bias=False,
            if_sweep=IfSweep(4, 6, 5),
            chunk_size=2,
            detector=DETECTOR_YIG,
            switch_delay=0,
            point_delay=0,
            hot_cold=HOT_COLD,
        )
        setup = TwoSbSetup(sis1_cid=1, sis2_cid=2, if_switch_cid=1, test_tone_cid=2)
        thread, devices, plots, errors = run_thread(SrrThread, params, setup)

        self.assertEqual(errors, [])
        data = thread.measure.data
        for side_band in ("upper", "lower"):
            np.testing.assert_allclose(data[side_band]["power_diff"], [20.0] * 5)
            np.testing.assert_allclose(
                np.array(data[side_band]["if"]), np.linspace(4e9, 6e9, 5)
            )
        np.testing.assert_allclose(data["y_factor"]["y_factor_lower"], [2.0] * 5)
        self.assertFalse(devices.tone_on)
        srr_curves = [p for dock, p in plots if dock == "SRR-IF curve"]
        self.assertEqual(len(srr_curves), 6)

    def test_if_balance_measures_bias_grid(self):
        params = IfBalanceParams(
            sis1_voltages=[5, 6],
            sis2_voltages=[5],
            if_sweep=IfSweep(4, 12, 4),
            precise_bias=False,
            switch_delay=0,
            point_delay=0,
        )
        thread, devices, plots, errors = run_thread(IfBalanceThread, params)

        self.assertEqual(errors, [])
        points = thread.measure.data["data"]
        self.assertEqual(
            [(p["sis1_voltage_set"], p["sis2_voltage_set"]) for p in points],
            [(5e-3, 5e-3), (6e-3, 5e-3)],
        )
        self.assertTrue(all(len(p["power_upper"]) == 4 for p in points))
        self.assertEqual(len(devices.yig_frequencies), 16)

    def test_rf_balance_turns_lo_off_and_sweeps_test_tone(self):
        params = PumpBalanceParams(
            source=SOURCE_RF,
            frequency_start=220,
            frequency_stop=221,
            frequency_points=2,
            bias_points=3,
            bias_delay=0,
        )
        setup = TwoSbSetup(sis1_cid=1, sis2_cid=2, lo_cid=1, test_tone_cid=2)
        thread, devices, plots, errors = run_thread(PumpBalanceThread, params, setup)

        self.assertEqual(errors, [])
        devices.lo.set_rf_output_state.assert_called_once_with(False)
        devices.test_tone.set_power.assert_called_once_with(4)
        self.assertEqual(devices.tone_frequency, 221e9)
        data = thread.measure.data["data"]
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["current1"], [10e-6] * 3)
        self.assertFalse(devices.tone_on)

    def test_optimization_fills_maps(self):
        params = OptimizationParams(
            lo_frequency=223,
            if_frequency=5,
            sis1_voltage_start=2.1,
            sis1_voltage_stop=2.2,
            sis1_voltage_step=0.1,
            sis2_voltage_start=2.1,
            sis2_voltage_stop=2.3,
            sis2_voltage_step=0.1,
            precise_bias=False,
            tone_delay=0,
            switch_delay=0,
            hot_cold=HOT_COLD,
        )
        setup = TwoSbSetup(sis1_cid=1, sis2_cid=2, if_switch_cid=1, test_tone_cid=2)
        setup_devices = FakeDevices(setup)
        thread = OptimizationThread(setup=setup, params=params, devices=setup_devices)
        maps = []
        thread.maps.connect(maps.append)
        thread.run()

        data = thread.measure.data
        expected_srr = sideband_rejection(-30, -32, -30, -32, -20, -40, -40, -20)
        self.assertEqual(len(data["srr_optimization"]["srr_upper"]), 2)
        self.assertEqual(len(data["srr_optimization"]["srr_upper"][0]), 3)
        for row in data["srr_optimization"]["srr_upper"]:
            np.testing.assert_allclose(row, [expected_srr[0]] * 3)
        for row in data["tn_optimization"]["tn_lower"]:
            np.testing.assert_allclose(row, [float(get_if_tn(-30, -32))] * 3)
        self.assertEqual(len(maps), 6)
        self.assertIsNone(maps[0]["tn_upper"][1][2])

    def test_stop_before_start_keeps_hardware_untouched(self):
        params = TnParams(precise_bias=False, hot_cold=HOT_COLD)
        setup = TwoSbSetup(sis1_cid=1, sis2_cid=2, if_switch_cid=1)
        devices = FakeDevices(setup)
        thread = TnThread(setup=setup, params=params, devices=devices)
        thread.request_stop()
        thread.run()

        devices.sis1.set_bias_voltage.assert_not_called()
        self.assertTrue(devices.closed)
        self.assertNotEqual(thread.measure.finished, "--")

    def test_device_error_is_reported(self):
        params = TnParams(
            precise_bias=False,
            if_sweep=IfSweep(4, 5, 2),
            switch_delay=0,
            point_delay=0,
            hot_cold=HOT_COLD,
        )
        setup = TwoSbSetup(sis1_cid=1, sis2_cid=2, if_switch_cid=1)
        devices = FakeDevices(setup)
        devices.read_power = Mock(
            side_effect=RuntimeError("Unable to read power meter")
        )
        thread = TnThread(setup=setup, params=params, devices=devices)
        errors = []
        thread.error.connect(errors.append)
        thread.run()

        self.assertEqual(errors, ["Unable to read power meter"])
        self.assertEqual(thread.measure.data["error"], "Unable to read power meter")
        self.assertEqual(devices.load, "cold")
