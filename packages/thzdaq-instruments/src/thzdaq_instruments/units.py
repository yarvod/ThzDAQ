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


# SI prefixes the UI offers, one table for every field, form and plot label
SI_PREFIXES = (
    ("p", 1e-12, "×10⁻¹²"),
    ("n", 1e-9, "×10⁻⁹"),
    ("µ", 1e-6, "×10⁻⁶"),
    ("m", 1e-3, "×10⁻³"),
    ("", 1.0, "×10⁰"),
    ("k", 1e3, "×10³"),
    ("M", 1e6, "×10⁶"),
    ("G", 1e9, "×10⁹"),
)
# Units that take a prefix; others (dBm, dB, deg) are shown as they are
PREFIXED_UNITS = ("Hz", "V", "A", "W", "s", "Pa", "Ohm", "K")
# Kelvin stops at milli: nobody wants kK or µK on a cryostat readout
UNIT_PREFIXES = {"K": ("m", "")}


def prefixes_for(unit: str):
    """(prefix, factor, note) choices for a unit; empty when it takes none."""
    if unit not in PREFIXED_UNITS:
        return ()
    allowed = UNIT_PREFIXES.get(unit)
    return tuple(p for p in SI_PREFIXES if allowed is None or p[0] in allowed)


def prefix_factor(prefix: str) -> float:
    for name, factor, _ in SI_PREFIXES:
        if name == prefix:
            return factor
    raise ValueError(f"Unknown SI prefix {prefix!r}")


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
