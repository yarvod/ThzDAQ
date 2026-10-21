"""Helpers shared by procedures: bias handling and state restore."""

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


def mv(voltage: float) -> str:
    return f"{voltage * 1e3:.3f} mV"
