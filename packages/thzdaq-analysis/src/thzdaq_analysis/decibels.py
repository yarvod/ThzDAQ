"""Power ratios in decibels."""

import math


def db_to_ratio(db: float) -> float:
    return 10 ** (db / 10)


def ratio_to_db(ratio: float) -> float:
    if ratio <= 0:
        raise ValueError("Ratio must be positive to convert to dB")
    return 10 * math.log10(ratio)
