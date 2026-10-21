"""Unit convention: SI inside the library (Hz, V, A, K, s, Pa), power in dBm, angles in degrees.

Scale factors convert UI values at the boundary: ``5 * GHZ`` -> Hz, ``hz / GHZ`` -> GHz.
"""

import math

GHZ = 1e9
MHZ = 1e6
KHZ = 1e3

MV = 1e-3
UV = 1e-6
MA = 1e-3
UA = 1e-6


def dbm_to_watt(dbm: float) -> float:
    return 1e-3 * 10 ** (dbm / 10)


def watt_to_dbm(watt: float) -> float:
    if watt <= 0:
        raise ValueError("Power must be positive to convert to dBm")
    return 10 * math.log10(watt / 1e-3)


def db_to_ratio(db: float) -> float:
    return 10 ** (db / 10)


def ratio_to_db(ratio: float) -> float:
    if ratio <= 0:
        raise ValueError("Ratio must be positive to convert to dB")
    return 10 * math.log10(ratio)


ZERO_CELSIUS = 273.15  # K
PSI = 6894.757293168  # Pa
HPA = 100.0  # Pa


def celsius_to_kelvin(celsius: float) -> float:
    return celsius + ZERO_CELSIUS


def kelvin_to_celsius(kelvin: float) -> float:
    return kelvin - ZERO_CELSIUS
