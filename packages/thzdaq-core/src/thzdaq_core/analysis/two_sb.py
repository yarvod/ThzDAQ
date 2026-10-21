"""Sideband separating (2SB) mixer calculations, powers in dBm."""

from typing import Tuple

from thzdaq_instruments.units import db_to_ratio, ratio_to_db

SIDE_BANDS = ("upper", "lower")


def test_tone_frequency(
    lo_frequency: float, if_frequency: float, side_band: str
) -> float:
    if side_band == "upper":
        return lo_frequency + if_frequency
    return lo_frequency - if_frequency


def power_difference(power_upper: float, power_lower: float, side_band: str) -> float:
    """Wanted IF channel minus the image one, dB."""
    if side_band == "upper":
        return power_upper - power_lower
    return power_lower - power_upper


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
    """SRR (dB) of the upper and lower channels.

    usb_* are IF channel powers with the test tone in the upper sideband,
    lsb_* with the tone in the lower one; p_* are hot/cold load powers.
    """
    m_dsb = (db_to_ratio(p_upper_hot) - db_to_ratio(p_upper_cold)) / (
        db_to_ratio(p_lower_hot) - db_to_ratio(p_lower_cold)
    )
    mu = db_to_ratio(usb_power_upper - usb_power_lower)
    ml = db_to_ratio(lsb_power_lower - lsb_power_upper)
    r1 = mu * (ml * m_dsb - 1) / (mu - m_dsb)
    r2 = ml * (mu - m_dsb) / (ml * m_dsb - 1)
    return ratio_to_db(abs(r1)), ratio_to_db(abs(r2))
