from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from utils.two_sb import SIDE_BANDS, sweep

IF_SWITCH_RIGOL = "Rigol DP832A"
IF_SWITCH_RS = "R&S HMP2030"
IF_SWITCH_KINDS = (IF_SWITCH_RIGOL, IF_SWITCH_RS)

DETECTOR_YIG = "YIG + power meter"
DETECTOR_SPECTRUM = "Spectrum analyzer"
DETECTORS = (DETECTOR_YIG, DETECTOR_SPECTRUM)

SOURCE_LO = "LO"
SOURCE_RF = "RF"


@dataclass
class TwoSbSetup:
    """Hardware shared by all 2SB measures."""

    sis1_cid: Optional[int] = None
    sis2_cid: Optional[int] = None
    lo_cid: Optional[int] = None
    lo_multiplier: float = 18
    test_tone_cid: Optional[int] = None
    test_tone_multiplier: float = 1
    if_switch_kind: str = IF_SWITCH_RIGOL
    if_switch_cid: Optional[int] = None
    if_switch_channel: int = 2
    # IF switch output state that routes the upper sideband channel to the detector
    upper_when_on: bool = True
    # Power supply channel feeding the YIG filter; 0 - not controlled
    yig_power_channel: int = 0
    yig: str = "yig_1"
    spectrum_cid: Optional[int] = None


@dataclass
class IfSweep:
    start: float = 4  # GHz
    stop: float = 12  # GHz
    points: int = 201

    def frequencies(self) -> np.ndarray:
        """Hz"""
        if self.points < 1:
            raise ValueError("IF points must be positive")
        return np.linspace(self.start, self.stop, int(self.points)) * 1e9


@dataclass
class IfBalanceParams:
    sis1_voltages: List[float] = field(default_factory=lambda: [5.0, 6.0])  # mV
    sis2_voltages: List[float] = field(default_factory=lambda: [5.0, 6.0])  # mV
    if_sweep: IfSweep = field(default_factory=IfSweep)
    precise_bias: bool = True
    switch_delay: float = 1  # s
    point_delay: float = 0.05  # s


@dataclass
class PumpBalanceParams:
    source: str = SOURCE_LO
    frequency_start: float = 220  # GHz, at the mixer
    frequency_stop: float = 265  # GHz
    frequency_points: int = 46
    source_power: float = 4  # dBm
    sis1_voltage_start: float = 2.4  # mV
    sis1_voltage_stop: float = 2.6  # mV
    sis2_voltage_start: float = 2.4  # mV
    sis2_voltage_stop: float = 2.6  # mV
    bias_points: int = 3
    bias_delay: float = 0.1  # s
    measure_power: bool = False

    def frequencies(self) -> np.ndarray:
        """Hz"""
        return (
            np.linspace(
                self.frequency_start, self.frequency_stop, int(self.frequency_points)
            )
            * 1e9
        )

    def voltages(self) -> List[Tuple[float, float]]:
        """Paired SIS1/SIS2 bias points, V"""
        points = int(self.bias_points)
        sis1 = np.linspace(self.sis1_voltage_start, self.sis1_voltage_stop, points)
        sis2 = np.linspace(self.sis2_voltage_start, self.sis2_voltage_stop, points)
        return [(v1 * 1e-3, v2 * 1e-3) for v1, v2 in zip(sis1, sis2)]


@dataclass
class HotColdParams:
    t_hot: float = 300  # K
    t_cold: float = 77  # K
    chopper_delay: float = 0.5  # s


@dataclass
class SrrParams:
    lo_frequency: float = 223  # GHz
    set_lo: bool = True
    sis1_voltage: float = 2.6  # mV
    sis2_voltage: float = 2.4  # mV
    precise_bias: bool = True
    if_sweep: IfSweep = field(default_factory=IfSweep)
    chunk_size: int = 10
    side_bands: Tuple[str, ...] = SIDE_BANDS
    detector: str = DETECTOR_YIG
    spectrum_rbw: float = 200  # kHz
    spectrum_vbw: float = 20  # kHz
    spectrum_span: float = 100  # kHz
    spectrum_averages: int = 5
    switch_delay: float = 1  # s
    point_delay: float = 0.05  # s
    measure_y_factor: bool = True
    hot_cold: HotColdParams = field(default_factory=HotColdParams)


@dataclass
class TnParams:
    lo_frequency: float = 263  # GHz
    set_lo: bool = True
    sis1_voltage: float = 2.5  # mV
    sis2_voltage: float = 2.5  # mV
    precise_bias: bool = True
    if_sweep: IfSweep = field(default_factory=IfSweep)
    side_bands: Tuple[str, ...] = SIDE_BANDS
    switch_delay: float = 1  # s
    point_delay: float = 0.01  # s
    hot_cold: HotColdParams = field(default_factory=HotColdParams)


@dataclass
class OptimizationParams:
    lo_frequency: float = 223  # GHz
    set_lo: bool = True
    if_frequency: float = 5  # GHz
    sis1_voltage_start: float = 2.1  # mV
    sis1_voltage_stop: float = 2.6  # mV
    sis1_voltage_step: float = 0.1  # mV
    sis2_voltage_start: float = 2.1  # mV
    sis2_voltage_stop: float = 2.6  # mV
    sis2_voltage_step: float = 0.1  # mV
    precise_bias: bool = True
    tone_delay: float = 0.5  # s
    switch_delay: float = 1  # s
    hot_cold: HotColdParams = field(default_factory=HotColdParams)

    def sis1_voltages(self) -> np.ndarray:
        """mV"""
        return sweep(
            self.sis1_voltage_start, self.sis1_voltage_stop, self.sis1_voltage_step
        )

    def sis2_voltages(self) -> np.ndarray:
        """mV"""
        return sweep(
            self.sis2_voltage_start, self.sis2_voltage_stop, self.sis2_voltage_step
        )
