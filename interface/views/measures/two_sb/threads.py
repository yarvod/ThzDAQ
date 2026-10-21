import logging
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Signal

from interface.views.measures.two_sb.devices import (
    SpectrumPeakDetector,
    TwoSbDevices,
    YigPowerDetector,
)
from interface.views.measures.two_sb.params import (
    DETECTOR_SPECTRUM,
    SOURCE_LO,
    HotColdParams,
    IfBalanceParams,
    OptimizationParams,
    PumpBalanceParams,
    SrrParams,
    TnParams,
    TwoSbSetup,
)
from store.base import MeasureModel, MeasureType
from threads import Thread
from utils.exceptions import DeviceConnectionError
from utils.two_sb import (
    SIDE_BANDS,
    bias_grid,
    noise_temperature,
    power_difference,
    sideband_rejection,
    split_chunks,
    test_tone_frequency,
)

logger = logging.getLogger(__name__)

# Iterative bias setting waits 1 s per iteration and can't be interrupted
BIAS_MAX_ITERATIONS = 30


class Docks:
    P_IF = "P-IF curve"
    Y_IF = "Y-IF curve"
    TN_IF = "Tn-IF curve"
    SRR_IF = "SRR-IF curve"
    I_F = "2SB I-F curve"


class StopMeasure(Exception):
    pass


class TwoSbThread(Thread):
    progress = Signal(int)
    plot = Signal(str, dict)
    error = Signal(str)

    measure_type: str = None

    def __init__(self, setup: TwoSbSetup, params, devices: TwoSbDevices = None):
        super().__init__()
        self.setup = setup
        self.params = params
        self.devices = devices or TwoSbDevices(setup)
        self.total_steps = 1
        self.step = 0
        self._stop_requested = False
        self._pre_exit_done = False
        self._initial_bias: Dict[str, Optional[float]] = {}
        self._test_tone_used = False
        self.measure = MeasureModel.objects.create(
            measure_type=self.measure_type,
            data={"setup": asdict(setup), "params": asdict(params)},
        )
        self.measure.save(finish=False)

    def request_stop(self):
        self._stop_requested = True

    def check_stop(self):
        if self._stop_requested:
            raise StopMeasure

    def run(self):
        try:
            self.check_stop()
            self.measure_run()
        except StopMeasure:
            logger.info(f"[{self.__class__.__name__}.run] Stopped by user")
        except (Exception, DeviceConnectionError) as e:
            logger.exception(f"[{self.__class__.__name__}.run] {e}")
            message = str(e) or e.__class__.__name__
            self.measure.data["error"] = message
            self.error.emit(message)
        finally:
            self.pre_exit()

    def measure_run(self):
        raise NotImplementedError

    def pre_exit(self, *args, **kwargs):
        if self._pre_exit_done:
            return
        self._pre_exit_done = True
        try:
            if self._test_tone_used:
                self._safe(lambda: self.devices.test_tone.set_rf_output_state(False))
            for name, voltage in self._initial_bias.items():
                if voltage is not None:
                    sis = getattr(self.devices, name)
                    self._safe(lambda: sis.set_bias_voltage(voltage))
        finally:
            self.measure.save()
            self._safe(self.devices.close)
            self.progress.emit(0)

    def _safe(self, func):
        try:
            func()
        except (Exception, DeviceConnectionError) as e:
            logger.error(f"[{self.__class__.__name__}.pre_exit] {e}")

    def advance(self, steps: int = 1):
        self.step += steps
        self.progress.emit(min(100, int(self.step / max(self.total_steps, 1) * 100)))

    @staticmethod
    def wait(seconds: float):
        if seconds > 0:
            time.sleep(seconds)

    def emit_plot(self, dock: str, curve: str, x: Iterable, y: Iterable):
        self.plot.emit(
            dock,
            {
                "x": [float(v) for v in x],
                "y": [float(v) for v in y],
                "curve": curve,
                "measure_id": self.measure.id,
            },
        )

    def set_bias(self, name: str, voltage: float, precise: bool):
        """voltage in V"""
        self.check_stop()
        sis = getattr(self.devices, name)
        if name not in self._initial_bias:
            self._initial_bias[name] = sis.get_bias_voltage()
        if precise:
            result = sis.set_bias_voltage_iterative(
                voltage, max_iterations=BIAS_MAX_ITERATIONS
            )
            if result is None:
                logger.warning(
                    f"[{self.__class__.__name__}.set_bias] {name} didn't reach {voltage * 1e3:.3f} mV"
                )
        else:
            sis.set_bias_voltage(voltage)

    def read_bias(self, name: str) -> Tuple[Optional[float], Optional[float]]:
        sis = getattr(self.devices, name)
        return sis.get_bias_voltage(), sis.get_bias_current()

    def set_lo(self, enabled: bool, frequency: float):
        if not enabled:
            return
        self.devices.lo.set_rf_output_state(True)
        self.devices.set_lo_frequency(frequency)

    def set_test_tone_output(self, value: bool):
        if value:
            self._test_tone_used = True
        self.devices.test_tone.set_rf_output_state(value)

    def test_tone_off_if_configured(self):
        if self.setup.test_tone_cid is not None:
            self.set_test_tone_output(False)

    def measure_hot_cold(
        self,
        data: Dict,
        frequencies: np.ndarray,
        side_bands: Sequence[str],
        point_delay: float,
        switch_delay: float,
        hot_cold: HotColdParams,
    ):
        """Y-factor and Tn of each IF channel with YIG + power meter."""
        if_switch = self.devices.if_switch
        chopper = self.devices.chopper
        if_switch.set_yig_power(True)
        for side_band in side_bands:
            data[f"p_{side_band}_hot"] = []
            data[f"p_{side_band}_cold"] = []
            self.check_stop()
            if_switch.select(side_band)
            self.wait(switch_delay)
            for load in ("cold", "hot"):
                self.check_stop()
                getattr(chopper, f"align_to_{load}")()
                self.wait(hot_cold.chopper_delay)
                powers = data[f"p_{side_band}_{load}"]
                for frequency in frequencies:
                    self.check_stop()
                    self.devices.set_yig_frequency(frequency)
                    self.wait(point_delay)
                    power = self.devices.read_power()
                    powers.append(power)
                    self.emit_plot(
                        Docks.P_IF, f"{side_band} {load}", [frequency / 1e9], [power]
                    )
                    self.advance()

            hot = np.array(data[f"p_{side_band}_hot"])
            cold = np.array(data[f"p_{side_band}_cold"])
            y_factor = hot - cold
            tn = noise_temperature(hot, cold, hot_cold.t_hot, hot_cold.t_cold)
            data[f"y_factor_{side_band}"] = y_factor.tolist()
            data[f"tn_{side_band}"] = tn.tolist()
            frequencies_ghz = frequencies / 1e9
            self.emit_plot(Docks.Y_IF, f"{side_band} Y", frequencies_ghz, y_factor)
            self.emit_plot(Docks.TN_IF, f"{side_band} Tn", frequencies_ghz, tn)
        chopper.align_to_cold()


class IfBalanceThread(TwoSbThread):
    measure_type = MeasureType.TWO_SB_IF_BALANCE
    params: IfBalanceParams

    def measure_run(self):
        p = self.params
        frequencies = p.if_sweep.frequencies()
        grid = bias_grid(p.sis1_voltages, p.sis2_voltages)
        self.total_steps = len(grid) * len(SIDE_BANDS) * len(frequencies)
        data = self.measure.data
        data.update({"if": frequencies.tolist(), "data": []})

        detector = YigPowerDetector(self.devices, p.point_delay)
        detector.prepare()
        for v1, v2 in grid:
            self.check_stop()
            self.set_bias("sis1", v1 * 1e-3, p.precise_bias)
            self.set_bias("sis2", v2 * 1e-3, p.precise_bias)
            sis1_voltage, sis1_current = self.read_bias("sis1")
            sis2_voltage, sis2_current = self.read_bias("sis2")
            point = {
                "sis1_voltage_set": v1 * 1e-3,
                "sis1_voltage": sis1_voltage,
                "sis1_current": sis1_current,
                "sis2_voltage_set": v2 * 1e-3,
                "sis2_voltage": sis2_voltage,
                "sis2_current": sis2_current,
                "power_upper": [],
                "power_lower": [],
            }
            data["data"].append(point)
            for side_band in SIDE_BANDS:
                self.check_stop()
                self.devices.if_switch.select(side_band)
                self.wait(p.switch_delay)
                for i, frequency in enumerate(frequencies):
                    self.check_stop()
                    power = detector.measure(frequency, first=i == 0)
                    point[f"power_{side_band}"].append(power)
                    self.emit_plot(
                        Docks.P_IF,
                        f"IF {side_band} {v1:.2f}/{v2:.2f} mV",
                        [frequency / 1e9],
                        [power],
                    )
                    self.advance()


class PumpBalanceThread(TwoSbThread):
    measure_type = MeasureType.TWO_SB_PUMP_BALANCE
    params: PumpBalanceParams

    def measure_run(self):
        p = self.params
        frequencies = p.frequencies()
        biases = p.voltages()
        self.total_steps = len(frequencies) * len(biases)
        data = self.measure.data
        data.update({"source": p.source, "data": []})

        if p.source == SOURCE_LO:
            source = self.devices.lo
            set_frequency = self.devices.set_lo_frequency
            if self.setup.test_tone_cid is not None:
                self.devices.test_tone.set_power(-80)
                self.set_test_tone_output(False)
        else:
            source = self.devices.test_tone
            set_frequency = self.devices.set_test_tone_frequency
            self._test_tone_used = True
            if self.setup.lo_cid is not None:
                self.devices.lo.set_power(-80)
                self.devices.lo.set_rf_output_state(False)
        source.set_power(p.source_power)
        source.set_rf_output_state(True)

        for frequency in frequencies:
            self.check_stop()
            set_frequency(frequency)
            point = {
                "frequency": frequency,
                "voltage1": [],
                "current1": [],
                "voltage2": [],
                "current2": [],
                "power": [],
            }
            data["data"].append(point)
            for v1, v2 in biases:
                self.check_stop()
                self.set_bias("sis2", v2, precise=False)
                self.set_bias("sis1", v1, precise=False)
                self.wait(p.bias_delay)
                voltage1, current1 = self.read_bias("sis1")
                voltage2, current2 = self.read_bias("sis2")
                point["voltage1"].append(voltage1)
                point["current1"].append(current1)
                point["voltage2"].append(voltage2)
                point["current2"].append(current2)
                if p.measure_power:
                    point["power"].append(self.devices.read_power())
                for name, voltage, current in (
                    ("SIS1", v1, current1),
                    ("SIS2", v2, current2),
                ):
                    if current is not None:
                        self.emit_plot(
                            Docks.I_F,
                            f"{name} {voltage * 1e3:.2f} mV",
                            [frequency / 1e9],
                            [current * 1e6],
                        )
                self.advance()


class SrrThread(TwoSbThread):
    measure_type = MeasureType.TWO_SB_SRR
    params: SrrParams

    def measure_run(self):
        p = self.params
        frequencies = p.if_sweep.frequencies()
        chunks = split_chunks(frequencies, p.chunk_size)
        lo_frequency = p.lo_frequency * 1e9
        sweeps = 2 if p.measure_y_factor else 1
        self.total_steps = (
            sweeps * len(p.side_bands) * len(SIDE_BANDS) * len(frequencies)
        )
        data = self.measure.data
        data.update({"lo": lo_frequency, "upper": {}, "lower": {}, "y_factor": {}})

        self.set_lo(p.set_lo, lo_frequency)
        self.set_bias("sis1", p.sis1_voltage * 1e-3, p.precise_bias)
        self.set_bias("sis2", p.sis2_voltage * 1e-3, p.precise_bias)
        data["sis1_voltage"], data["sis1_current"] = self.read_bias("sis1")
        data["sis2_voltage"], data["sis2_current"] = self.read_bias("sis2")

        if p.detector == DETECTOR_SPECTRUM:
            detector = SpectrumPeakDetector(
                self.devices,
                rbw=p.spectrum_rbw,
                vbw=p.spectrum_vbw,
                span=p.spectrum_span,
                averages=p.spectrum_averages,
            )
        else:
            detector = YigPowerDetector(self.devices, p.point_delay)
        detector.prepare()
        if p.measure_y_factor:
            self.devices.chopper.align_to_hot()
        self.set_test_tone_output(True)

        for side_band in p.side_bands:
            result = {
                "LO": lo_frequency,
                "side_band": side_band,
                "power_upper": [],
                "power_lower": [],
                "power_diff": [],
                "if": [],
            }
            data[side_band] = result
            for chunk in chunks:
                for channel in SIDE_BANDS:
                    self.check_stop()
                    self.devices.if_switch.select(channel)
                    self.wait(p.switch_delay)
                    for i, frequency in enumerate(chunk):
                        self.check_stop()
                        self.devices.set_test_tone_frequency(
                            test_tone_frequency(lo_frequency, frequency, side_band)
                        )
                        power = detector.measure(frequency, first=i == 0)
                        result[f"power_{channel}"].append(power)
                        self.emit_plot(
                            Docks.P_IF,
                            f"tone {side_band} IF {channel}",
                            [frequency / 1e9],
                            [power],
                        )
                        self.advance()

                size = len(chunk)
                diff = power_difference(
                    result["power_upper"][-size:],
                    result["power_lower"][-size:],
                    side_band,
                )
                result["power_diff"].extend(diff.tolist())
                result["if"].extend(chunk.tolist())
                self.emit_plot(Docks.SRR_IF, f"{side_band}", chunk / 1e9, diff)

        self.set_test_tone_output(False)
        if p.measure_y_factor:
            self.measure_hot_cold(
                data["y_factor"],
                frequencies,
                p.side_bands,
                p.point_delay,
                p.switch_delay,
                p.hot_cold,
            )


class TnThread(TwoSbThread):
    measure_type = MeasureType.TWO_SB_TN
    params: TnParams

    def measure_run(self):
        p = self.params
        frequencies = p.if_sweep.frequencies()
        lo_frequency = p.lo_frequency * 1e9
        self.total_steps = len(p.side_bands) * 2 * len(frequencies)
        data = self.measure.data
        data.update({"lo": lo_frequency, "if": frequencies.tolist()})

        self.test_tone_off_if_configured()
        self.set_lo(p.set_lo, lo_frequency)
        self.set_bias("sis1", p.sis1_voltage * 1e-3, p.precise_bias)
        self.set_bias("sis2", p.sis2_voltage * 1e-3, p.precise_bias)
        data["sis1_voltage"], data["sis1_current"] = self.read_bias("sis1")
        data["sis2_voltage"], data["sis2_current"] = self.read_bias("sis2")
        self.measure_hot_cold(
            data,
            frequencies,
            p.side_bands,
            p.point_delay,
            p.switch_delay,
            p.hot_cold,
        )


class OptimizationThread(TwoSbThread):
    measure_type = MeasureType.TWO_SB_OPTIMIZATION
    params: OptimizationParams
    maps = Signal(dict)

    def measure_run(self):
        p = self.params
        sis1_voltages = p.sis1_voltages()
        sis2_voltages = p.sis2_voltages()
        lo_frequency = p.lo_frequency * 1e9
        if_frequency = p.if_frequency * 1e9
        self.total_steps = len(sis1_voltages) * len(sis2_voltages)

        def grid():
            return [[None] * len(sis2_voltages) for _ in sis1_voltages]

        data = self.measure.data
        srr = {
            "upper": {"power_upper": [], "power_lower": []},
            "lower": {"power_upper": [], "power_lower": []},
            "srr_upper": grid(),
            "srr_lower": grid(),
        }
        tn = {
            "power_upper_hot": [],
            "power_lower_hot": [],
            "power_upper_cold": [],
            "power_lower_cold": [],
            "tn_upper": grid(),
            "tn_lower": grid(),
        }
        data.update(
            {
                "if": if_frequency,
                "lo": lo_frequency,
                "voltage_1": (sis1_voltages * 1e-3).tolist(),
                "voltage_2": (sis2_voltages * 1e-3).tolist(),
                "current_1": grid(),
                "current_2": grid(),
                "srr_optimization": srr,
                "tn_optimization": tn,
            }
        )

        if_switch = self.devices.if_switch
        chopper = self.devices.chopper
        self.set_lo(p.set_lo, lo_frequency)
        if_switch.set_yig_power(True)
        self.devices.set_yig_frequency(if_frequency)
        chopper.align_to_hot()

        for i, v1 in enumerate(sis1_voltages):
            self.check_stop()
            self.set_bias("sis1", v1 * 1e-3, p.precise_bias)
            for j, v2 in enumerate(sis2_voltages):
                self.check_stop()
                self.set_bias("sis2", v2 * 1e-3, p.precise_bias)
                data["current_1"][i][j] = self.read_bias("sis1")[1]
                data["current_2"][i][j] = self.read_bias("sis2")[1]

                self.set_test_tone_output(True)
                self.wait(p.tone_delay)
                for tone in SIDE_BANDS:
                    self.devices.set_test_tone_frequency(
                        test_tone_frequency(lo_frequency, if_frequency, tone)
                    )
                    self.wait(p.tone_delay)
                    for channel in SIDE_BANDS:
                        self.check_stop()
                        if_switch.select(channel)
                        self.wait(p.switch_delay)
                        srr[tone][f"power_{channel}"].append(self.read_settled_power())

                self.set_test_tone_output(False)
                for channel in SIDE_BANDS:
                    self.check_stop()
                    if_switch.select(channel)
                    self.wait(p.switch_delay)
                    for load in ("cold", "hot"):
                        getattr(chopper, f"align_to_{load}")()
                        self.wait(p.hot_cold.chopper_delay)
                        tn[f"power_{channel}_{load}"].append(self.devices.read_power())

                for channel in SIDE_BANDS:
                    tn[f"tn_{channel}"][i][j] = float(
                        noise_temperature(
                            tn[f"power_{channel}_hot"][-1],
                            tn[f"power_{channel}_cold"][-1],
                            p.hot_cold.t_hot,
                            p.hot_cold.t_cold,
                        )
                    )
                srr["srr_upper"][i][j], srr["srr_lower"][i][j] = sideband_rejection(
                    p_upper_hot=tn["power_upper_hot"][-1],
                    p_upper_cold=tn["power_upper_cold"][-1],
                    p_lower_hot=tn["power_lower_hot"][-1],
                    p_lower_cold=tn["power_lower_cold"][-1],
                    usb_power_upper=srr["upper"]["power_upper"][-1],
                    usb_power_lower=srr["upper"]["power_lower"][-1],
                    lsb_power_upper=srr["lower"]["power_upper"][-1],
                    lsb_power_lower=srr["lower"]["power_lower"][-1],
                )
                logger.info(
                    f"[{self.__class__.__name__}] V1={v1:.3f} mV V2={v2:.3f} mV "
                    f"Tn_u={tn['tn_upper'][i][j]:.1f} K Tn_l={tn['tn_lower'][i][j]:.1f} K "
                    f"SRR_u={srr['srr_upper'][i][j]:.2f} dB SRR_l={srr['srr_lower'][i][j]:.2f} dB"
                )
                self.maps.emit(
                    {
                        "voltage_1": sis1_voltages.tolist(),
                        "voltage_2": sis2_voltages.tolist(),
                        "tn_upper": deepcopy(tn["tn_upper"]),
                        "tn_lower": deepcopy(tn["tn_lower"]),
                        "srr_upper": deepcopy(srr["srr_upper"]),
                        "srr_lower": deepcopy(srr["srr_lower"]),
                    }
                )
                self.advance()

        chopper.align_to_cold()

    def read_settled_power(self) -> float:
        # Power meter keeps averaging over the IF switch transient, drop two readings
        self.devices.read_power()
        self.devices.read_power()
        return self.devices.read_power()
