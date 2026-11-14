from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import CURRENT_VS_COIL_CURRENT, DEMAGNETIZATION
from thzdaq_instruments.capabilities import CurrentSource, VoltageCurrentMeter
from thzdaq_instruments.quantities import CURRENT_SET
from thzdaq_instruments.units import MA, UA

from thzdaq_core.domain.measurements.procedures.common import (
    COIL_CURRENT_MA,
    CURRENT_UA,
)
from thzdaq_core.domain.parameters import FloatParameter, SweepParameter
from thzdaq_api.measurements import PlotInfo, plot_caption
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.sis.demagnetization import demagnetization_currents


class Demagnetize(Procedure):
    name = DEMAGNETIZATION
    slot_modes = {"coil": EXCLUSIVE}
    leaves = ("coil",)  # at the centre: what it is for
    title = "SIS demagnetization"
    description = (
        "Sweep the coil current over the full range, then swing it around the "
        "centre with a shrinking amplitude and leave it at the centre."
    )
    guide = (
        "Takes trapped flux out of the junction and the magnet: the coil swings "
        "with a shrinking amplitude and stops at the centre. Run it after a quench, "
        "a thermal cycle or when the Josephson current cannot be suppressed as "
        "before; then find the suppressing current again "
        f"({CURRENT_VS_COIL_CURRENT}). Keep minimum and maximum within the coil "
        "limits."
    )
    requires = {"coil": CurrentSource}
    plots = (
        PlotInfo(
            "coil", "Coil current", "coil", "step", "current",
            x_label="Step", y_label="Current, mA", y_scale=MA,
            caption=plot_caption("I–n", "Coil current (demagnetization step)"),
        ),
    )  # fmt: skip

    minimum = FloatParameter(
        "Minimum current",
        default=-30 * MA,
        unit="A",
        display_unit="mA",
        display_scale=MA,
        applies=("coil", CURRENT_SET.key),
    )
    maximum = FloatParameter(
        "Maximum current",
        default=30 * MA,
        unit="A",
        display_unit="mA",
        display_scale=MA,
        applies=("coil", CURRENT_SET.key),
    )
    step = FloatParameter(
        "Current step",
        default=5 * MA,
        minimum=1e-6,
        unit="A",
        display_unit="mA",
        display_scale=MA,
    )
    step_delay = FloatParameter("Step delay", default=0.05, minimum=0, unit="s")

    def check(self):
        if self.maximum <= self.minimum:
            return ["maximum current must be above the minimum"]
        return []

    def estimate_steps(self) -> int:
        return len(demagnetization_currents(self.minimum, self.maximum, self.step))

    def run(self, ctx) -> None:
        coil = ctx["coil"]
        for index, current in enumerate(
            demagnetization_currents(self.minimum, self.maximum, self.step)
        ):
            ctx.check_cancel()
            coil.set_current(current)
            ctx.record("coil", step=index, current=current)
            ctx.sleep(self.step_delay)
            ctx.progress()


class CLCurve(Procedure):
    name = CURRENT_VS_COIL_CURRENT
    slot_modes = {"coil": EXCLUSIVE, "bias": READ}
    title = "SIS Josephson suppression"
    description = (
        "Sweep the magnet coil current and read the bias current: finds the "
        "coil current that suppresses the Josephson current."
    )
    guide = (
        "Finds the coil current that suppresses the Josephson current: the SIS "
        "current against the coil current at a small fixed bias. Set the bias first "
        "(below the gap, where the Josephson current shows, about a third of the "
        "gap or less) with the LO off. The minimum of the current is the coil "
        "current to set and keep for the other measurements. A curve that changed "
        f"shape asks for {DEMAGNETIZATION} first."
    )
    requires = {"coil": CurrentSource, "bias": VoltageCurrentMeter}
    plots = (
        PlotInfo(
            "cl", "I-CL", "cl", "coil_current", "current",
            x_label=COIL_CURRENT_MA, y_label=CURRENT_UA,
            x_scale=MA, y_scale=UA,
            caption=plot_caption("I–CL", "SIS current (coil current)"),
        ),
    )  # fmt: skip

    coil_current = SweepParameter(
        "Coil current",
        default=(0.0, 30e-3, 61),
        unit="A",
        display_unit="mA",
        display_scale=MA,
        applies=("coil", CURRENT_SET.key),
    )
    step_delay = FloatParameter("Step delay", default=0.1, minimum=0, unit="s")

    def estimate_steps(self) -> int:
        return self.coil_current.points

    def run(self, ctx) -> None:
        coil, bias = ctx["coil"], ctx["bias"]
        for current in self.coil_current.values():
            ctx.check_cancel()
            coil.set_current(current)
            ctx.sleep(self.step_delay)
            reading = bias.measure()
            ctx.record(
                "cl",
                coil_current=current,
                voltage=reading.voltage,
                current=reading.current,
            )
            ctx.progress()
