"""What procedures share: parameters (one definition, a default per procedure), the
groups a form shows them in, axis labels of plots, bias handling, state restore,
hot/cold checks."""

import math
from typing import Iterable, List, Optional, Tuple

from thzdaq_instruments.capabilities import VoltageCurrentMeter, VoltageSource
from thzdaq_instruments.quantities import ANGLE, VOLTAGE_SET
from thzdaq_instruments.units import GHZ, MV

from thzdaq_core.domain.parameters import FloatParameter, SweepParameter

BIAS = (VoltageSource, VoltageCurrentMeter)

# Axis labels of plots; those of traces (POWER_DBM, S_DB) are the contract's
CURRENT_UA = "Current, μA"
COIL_CURRENT_MA = "Coil current, mA"
VOLTAGE_MV = "Voltage, mV"
IF_GHZ = "IF, GHz"
FREQUENCY_GHZ = "Frequency, GHz"
Y_DB = "Y, dB"
TN_K = "Tn, K"

Range = Tuple[float, float, int]


class Group:
    """Titles of the parts of a form parameters are shown in."""

    BIAS = "Bias"
    LO = "LO"
    IF = "IF"
    TEST_TONE = "RF test tone"
    SOURCE = "Source"
    DETECTOR = "Detector"
    VNA = "VNA"
    HOT_COLD = "Hot/cold"
    GRID = "Grid"
    TIMING = "Timing"


# Parameters several procedures have; the default stays each procedure's own
class SettleTime(FloatParameter):
    def __init__(self, default: float, maximum: Optional[float] = None):
        super().__init__(
            "Settle time",
            default=default,
            minimum=0,
            maximum=maximum,
            unit="s",
            group=Group.TIMING,
        )


class FirstPointDelay(FloatParameter):
    def __init__(self, default: float, maximum: Optional[float] = None):
        super().__init__(
            "First point delay",
            default=default,
            minimum=0,
            maximum=maximum,
            unit="s",
            help="The bias source needs longer to reach the first point",
            group=Group.TIMING,
        )


class PointDelay(FloatParameter):
    def __init__(self, default: float):
        super().__init__(
            "Point delay", default=default, minimum=0, unit="s", group=Group.TIMING
        )


class BiasVoltage(SweepParameter):
    def __init__(self, default: Range):
        super().__init__(
            "Bias voltage",
            default=default,
            unit="V",
            display_unit="mV",
            display_scale=MV,
            applies=("bias", VOLTAGE_SET.key),
            group=Group.BIAS,
        )


class IFSweep(SweepParameter):
    def __init__(self, default: Range = (4 * GHZ, 12 * GHZ, 201)):
        super().__init__(
            "IF",
            default=default,
            unit="Hz",
            display_unit="GHz",
            display_scale=GHZ,
            group=Group.IF,
        )


class IFFrequency(FloatParameter):
    def __init__(self, default: float):
        super().__init__(
            "IF",
            default=default,
            minimum=0,
            unit="Hz",
            display_unit="GHz",
            display_scale=GHZ,
            group=Group.IF,
        )


class HotLoad(FloatParameter):
    def __init__(self):
        super().__init__(
            "Hot load", default=300.0, minimum=0, unit="K", group=Group.HOT_COLD
        )


class ColdLoad(FloatParameter):
    def __init__(self):
        super().__init__(
            "Cold load", default=77.0, minimum=0, unit="K", group=Group.HOT_COLD
        )


class LoadDelay(FloatParameter):
    def __init__(self, default: float):
        super().__init__(
            "Load switch delay",
            default=default,
            minimum=0,
            unit="s",
            group=Group.HOT_COLD,
        )


class GridAngle(SweepParameter):
    def __init__(self, default: Range, max_points: int):
        super().__init__(
            "Grid angle",
            default=default,
            unit="deg",
            max_points=max_points,
            applies=("grid", ANGLE.key),
            group=Group.GRID,
        )


class GridSpeed(FloatParameter):
    def __init__(self):
        super().__init__(
            "Grid speed",
            default=180.0,
            minimum=1e-3,
            unit="deg/s",
            help="Wait |Δangle| / speed after each rotation",
            group=Group.GRID,
        )


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


def load_problems(t_hot: float, t_cold: float) -> List[str]:
    """What is wrong with the hot/cold load temperatures, for Procedure.check()."""
    return [] if t_hot > t_cold else ["hot load must be warmer than the cold one"]


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
