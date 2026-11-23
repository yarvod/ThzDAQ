from contextlib import closing
from typing import List

from thzdaq_api.analysis import IV
from thzdaq_api.leases import EXCLUSIVE
from thzdaq_api.procedures import (
    CURRENT_VS_COIL_CURRENT,
    CURRENT_VS_VOLTAGE,
    CURRENT_VS_VOLTAGE_FAST,
)
from thzdaq_instruments.capabilities import (
    VoltageCurrentMeter,
    VoltageSource,
    VoltageSweep,
)
from thzdaq_instruments.units import MV, UA

from thzdaq_core.domain.measurements.procedures.common import (
    IV_CAPTION,
    CURRENT_UA,
    VOLTAGE_MV,
    BiasVoltage,
    FirstPointDelay,
    Group,
    SettleTime,
)
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.parameters import FloatParameter

# The I-V graph: both I-V curves draw into it and have it analysed
IV_PLOT = PlotInfo(
    key="iv",
    title="I-V",
    table="iv",
    x="voltage",
    y="current",
    x_label=VOLTAGE_MV,
    y_label=CURRENT_UA,
    x_scale=MV,
    y_scale=UA,
    analysis=IV,
    caption=IV_CAPTION,
)


class IVCurve(Procedure):
    name = CURRENT_VS_VOLTAGE
    slot_modes = {"bias": EXCLUSIVE}
    title = "SIS I-V curve"
    description = "Sweep the bias voltage and read voltage and current."
    guide = (
        "The first look at a junction and the check before any other SIS "
        "measurement. Unpumped (LO off) it shows the gap, the normal-state "
        "resistance Rn and the subgap leakage; with the LO on, the photon steps "
        "below the gap tell how strongly the mixer is pumped. Sweep from 0 up to "
        "above the gap (the default 0:7:351 mV) and stay within the range "
        "describe_device gives for the bias. A Josephson peak near zero bias means "
        f"the coil does not suppress it yet ({CURRENT_VS_COIL_CURRENT}). The plot's "
        "I-V analysis gives Rn and the gap."
    )
    requires = {"bias": (VoltageSource, VoltageCurrentMeter)}
    plots = (IV_PLOT,)

    voltage = BiasVoltage((0.0, 7e-3, 351))
    settle_time = SettleTime(0.01, maximum=10)
    first_point_delay = FirstPointDelay(0.5, maximum=10)

    def estimate_steps(self) -> int:
        return self.voltage.points

    def run(self, ctx) -> None:
        bias = ctx["bias"]
        for index, voltage in enumerate(self.voltage.values()):
            ctx.check_cancel()
            bias.set_voltage(voltage)
            ctx.sleep(self.first_point_delay if index == 0 else self.settle_time)
            reading = bias.measure()
            ctx.record(
                "iv",
                voltage_set=voltage,
                voltage=reading.voltage,
                current=reading.current,
            )
            ctx.progress()


class FastIVCurve(Procedure):
    name = CURRENT_VS_VOLTAGE_FAST
    slot_modes = {"bias": EXCLUSIVE}
    title = "SIS I-V curve (fast)"
    description = "The bias block sweeps the voltage and reads every point itself."
    guide = (
        "The same I-V curve, swept by the bias block itself: it steps and reads "
        "every point on its own, far faster than "
        f"{CURRENT_VS_VOLTAGE}, which sets and reads each point from here. The "
        "bench step and rate of the bias's voltage_set bound the sweep: its step "
        "(range / (points − 1)) may not exceed the step, nor step / time per point "
        "the rate, or the sweep is refused before it starts. Use "
        f"{CURRENT_VS_VOLTAGE} when each point needs a settle of its own (a slow "
        "circuit, a pumped junction that drifts). The plot's I-V analysis gives Rn "
        "and the gap as for the other curve."
    )
    requires = {"bias": (VoltageSource, VoltageSweep)}
    plots = (IV_PLOT,)

    voltage = BiasVoltage((0.0, 7e-3, 351))
    dwell = FloatParameter(
        "Time per point",
        default=2e-3,
        minimum=1e-3,
        maximum=1.0,
        unit="s",
        display_unit="ms",
        display_scale=1e-3,
        help="The block holds each point so long before it reads it",
        group=Group.TIMING,
    )
    first_point_delay = FirstPointDelay(0.5, maximum=10)

    def estimate_steps(self) -> int:
        return self.voltage.points

    def check(self) -> List[str]:
        return [] if self.voltage.points > 1 else ["a sweep needs two points at least"]

    def run(self, ctx) -> None:
        bias = ctx["bias"]
        start, stop = self.voltage.start, self.voltage.stop
        bias.set_voltage(start)
        ctx.sleep(self.first_point_delay)
        with closing(
            bias.sweep_voltage(start, stop, self.voltage.step, self.dwell)
        ) as sweep:
            for reading in sweep:
                ctx.check_cancel()
                ctx.record("iv", voltage=reading.voltage, current=reading.current)
                ctx.progress()
