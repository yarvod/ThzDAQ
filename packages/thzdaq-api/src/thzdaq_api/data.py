"""Values of measurement data as JSON: the encoding of thzdaq-measurement files,
and of records as run events carry them.

JSON has no complex numbers and no NaN or infinity: a complex value is
{"__complex__": [re, im]}, a non-finite float {"__float__": "nan"}.
"""

import math
from typing import Any


def encode_values(value: Any) -> Any:
    if isinstance(value, complex):
        return {"__complex__": [value.real, value.imag]}
    if isinstance(value, float) and not math.isfinite(value):
        return {"__float__": repr(value)}
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
