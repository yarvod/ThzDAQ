"""Values of measurement data: numbers that know what they are (Measured), and
their encoding as JSON in thzdaq-measurement files and in records as run
events carry them.

JSON has no complex numbers and no NaN or infinity: a complex value is
{"__complex__": [re, im]}, a non-finite float {"__float__": "nan"}.
"""

import math
from typing import Any


class Measured(float):
    """A number read from a device or swept, in SI units, with its unit, its
    title and where it was read ("<ref>/<key>"; empty when it was not). In
    calculations it is a plain float; a script records it with what it knows."""

    unit: str
    title: str
    source: str

    def __new__(cls, value: float, unit: str = "", title: str = "", source: str = ""):
        measured = super().__new__(cls, value)
        measured.unit, measured.title, measured.source = unit, title, source
        return measured

    def __repr__(self) -> str:
        return f"{float(self)!r} {self.unit}".rstrip()


def encode_values(value: Any) -> Any:
    if isinstance(value, complex):
        return {"__complex__": [value.real, value.imag]}
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else {"__float__": repr(value)}
    if isinstance(value, dict):
        return {key: encode_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_values(item) for item in value]
    if hasattr(value, "item") and callable(value.item):  # numpy scalars
        return encode_values(value.item())
    return value


def decode_values(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__complex__"}:
            real, imag = value["__complex__"]
            return complex(real, imag)
        if set(value) == {"__float__"}:
            return float(value["__float__"])
        return {key: decode_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_values(item) for item in value]
    return value
