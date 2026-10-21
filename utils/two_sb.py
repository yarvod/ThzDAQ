"""Pure helpers for 2SB (sideband separating) mixer measurements."""

import re
from itertools import product
from typing import Iterable, List, Literal, Sequence, Tuple

import numpy as np

from utils.functions import calc_m_dsb, calc_r1, calc_r2, get_tn, to_db_10

SideBand = Literal["upper", "lower"]
SIDE_BANDS: Tuple[SideBand, SideBand] = ("upper", "lower")


def parse_float_list(text: str) -> List[float]:
    """Parse values separated by commas, semicolons or spaces."""
    return [float(value) for value in re.split(r"[,;\s]+", text.strip()) if value]


def bias_grid(
    sis1_voltages: Iterable[float], sis2_voltages: Iterable[float]
) -> List[Tuple[float, float]]:
    return list(product(sis1_voltages, sis2_voltages))


def sweep(start: float, stop: float, step: float) -> np.ndarray:
    """Inclusive range with a fixed step (stop is kept if it lies on the grid)."""
    if step <= 0:
        raise ValueError("Step must be positive")
    if stop < start:
        raise ValueError("Stop must be greater than or equal to start")
    count = int(np.floor((stop - start) / step + 1e-9)) + 1
    return start + step * np.arange(count)


def test_tone_frequency(lo_frequency: float, if_frequency: float, side_band: str):
    if side_band == "upper":
        return lo_frequency + if_frequency
    return lo_frequency - if_frequency


def split_chunks(values: Sequence[float], chunk_size: int) -> List[np.ndarray]:
    values = np.asarray(values)
    chunk_size = max(1, int(chunk_size))
    return [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]


def power_difference(
    power_upper: Sequence[float], power_lower: Sequence[float], side_band: str
) -> np.ndarray:
    """Power of the wanted IF channel minus the image one, dB."""
    upper = np.asarray(power_upper, dtype=float)
    lower = np.asarray(power_lower, dtype=float)
    return upper - lower if side_band == "upper" else lower - upper


def db_to_linear(value):
    return 10 ** (np.asarray(value, dtype=float) / 10)


def noise_temperature(hot_dbm, cold_dbm, t_hot: float = 300, t_cold: float = 77):
    y = db_to_linear(hot_dbm) / db_to_linear(cold_dbm)
    return get_tn(y, th=t_hot, tc=t_cold)


def sideband_rejection(
    p_upper_hot: float,
    p_upper_cold: float,
    p_lower_hot: float,
    p_lower_cold: float,
    usb_power_upper: float,
    usb_power_lower: float,
    lsb_power_upper: float,
    lsb_power_lower: float,
) -> Tuple[float, float]:
    """SRR (dB) of upper and lower channels from test tone and hot/cold powers (dBm).

    usb_* are IF channel powers with the test tone in the upper sideband,
    lsb_* with the test tone in the lower sideband.
    """
    m_dsb = calc_m_dsb(
        db_to_linear(p_upper_hot),
        db_to_linear(p_upper_cold),
        db_to_linear(p_lower_hot),
        db_to_linear(p_lower_cold),
    )
    mu = db_to_linear(usb_power_upper) / db_to_linear(usb_power_lower)
    ml = db_to_linear(lsb_power_lower) / db_to_linear(lsb_power_upper)
    return (
        float(to_db_10(calc_r1(mu, ml, m_dsb))),
        float(to_db_10(calc_r2(mu, ml, m_dsb))),
    )
