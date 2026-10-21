"""IF amplifier noise from SIS shot noise at two bias points above the gap."""

import math
from typing import Sequence, Tuple

ELEMENTARY_CHARGE = 1.602176634e-19  # C
BOLTZMANN = 1.380649e-23  # J/K


def linear_fit(x: Sequence[float], y: Sequence[float]) -> Tuple[float, float]:
    """Least squares y = slope * x + intercept."""
    n = len(x)
    if n < 2:
        raise ValueError("need at least two points")
    mean_x, mean_y = sum(x) / n, sum(y) / n
    sxx = sum((xi - mean_x) ** 2 for xi in x)
    if sxx == 0:
        raise ValueError("x values are all equal")
    slope = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / sxx
    return slope, mean_y - slope * mean_x


def dynamic_resistance(voltages: Sequence[float], currents: Sequence[float]) -> float:
    """dV/dI around a bias point, Ohm."""
    slope, _ = linear_fit(voltages, currents)
    return 1 / slope


def shot_noise_temperature(
    current: float, voltage: float, rd: float, t_sis: float = 4.0
) -> float:
    """Equivalent IF noise temperature of the SIS shot noise, K."""
    x = ELEMENTARY_CHARGE * voltage / (BOLTZMANN * t_sis)
    return ELEMENTARY_CHARGE * rd * current / (2 * BOLTZMANN * math.tanh(x))


def mismatch(z_sis: float, z_load: float = 50.0) -> float:
    """Power transmission 1 - |Γ|² between the SIS and the IF chain."""
    return 1 - abs((z_sis - z_load) / (z_sis + z_load)) ** 2


def amplifier_temperature(
    power1_w: float,
    power2_w: float,
    t1: float,
    t2: float,
    m1: float,
    m2: float,
) -> float:
    """IF amplifier noise, K, from IF powers (W) at bias points 1 and 2."""
    y = power2_w / power1_w
    if y == 1:
        return math.nan
    return (y * t1 * m1 - m2 * t2) / (1 - y)
