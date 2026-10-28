"""Helpers shared by procedures: bias handling, state restore, hot/cold checks."""

import math
from typing import Iterable

from thzdaq_instruments.capabilities import VoltageCurrentMeter, VoltageSource

BIAS = (VoltageSource, VoltageCurrentMeter)
PRECISE_ITERATIONS = 30


def set_bias(port, voltage: float, precise: bool = False) -> None:
    """Set a bias voltage; `precise` corrects it by readback when the port can."""
    if precise and hasattr(port, "set_voltage_precise"):
        port.set_voltage_precise(voltage, max_iterations=PRECISE_ITERATIONS)
    else:
        port.set_voltage(voltage)


def restore_bias_on_exit(ctx, port) -> None:
    initial = port.get_voltage()
    ctx.on_exit(lambda: port.set_voltage(initial))


def restore_angle_on_exit(ctx, rotator) -> None:
    initial = rotator.get_angle()
    ctx.on_exit(lambda: rotator.rotate_to(initial))


def warn_without_contrast(ctx, temperatures: Iterable[float], where: str) -> None:
    """Tn is undefined where hot is not above cold (Y <= 0 dB) and such points
    are not drawn: the log says why a curve is short or missing."""
    values = list(temperatures)
    missing = sum(1 for t in values if not math.isfinite(t))
    if not missing:
        return
    if missing == len(values):
        ctx.log(
            f"{where}: hot is not above cold at any point (Y <= 0 dB), no Tn: "
            "did the load switch?"
        )
    else:
        ctx.log(f"{where}: no Tn at {missing} of {len(values)} points (Y <= 0 dB)")


def mv(voltage: float) -> str:
    return f"{voltage * 1e3:.3f} mV"
