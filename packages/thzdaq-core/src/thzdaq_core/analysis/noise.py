"""Hot/cold load (Y-factor) noise temperature."""

import math

from thzdaq_instruments.units import db_to_ratio


def y_factor_db(hot_dbm: float, cold_dbm: float) -> float:
    return hot_dbm - cold_dbm


def noise_temperature(
    hot_dbm: float, cold_dbm: float, t_hot: float = 300.0, t_cold: float = 77.0
) -> float:
    """Receiver noise temperature, K. NaN when Y <= 1 (no usable hot/cold contrast)."""
    y = db_to_ratio(hot_dbm - cold_dbm)
    if y <= 1:
        return math.nan
    return (t_hot - y * t_cold) / (y - 1)


def match_hot_cold(hot, cold, window: int = 10):
    """Pair hot and cold readings measured at (nearly) the same bias.

    hot, cold: sequences of (voltage, power_dbm) in sweep order. Each hot point
    is paired with the cold point of the closest voltage among `window`
    neighbours of the same index. Returns [(voltage, hot_dbm, cold_dbm)].
    """
    pairs = []
    count = min(len(hot), len(cold))
    left = window // 2
    right = left + window % 2
    for index in range(count):
        low = max(index - left, 0)
        high = min(index + right + 1, len(cold))
        voltage, hot_power = hot[index]
        nearest = min(range(low, high), key=lambda j: abs(cold[j][0] - voltage))
        pairs.append((voltage, hot_power, cold[nearest][1]))
    return pairs
