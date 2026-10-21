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
