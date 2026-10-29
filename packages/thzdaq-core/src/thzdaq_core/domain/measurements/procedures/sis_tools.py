from thzdaq_api.procedures import CL_CURVE, DEMAGNETIZE
from thzdaq_instruments.capabilities import CurrentSource, VoltageCurrentMeter
from thzdaq_instruments.units import MA, UA

from thzdaq_core.domain.measurements.procedures.common import (
    COIL_CURRENT_MA,
    CURRENT_UA,
)
from thzdaq_core.domain.parameters import FloatParameter, SweepParameter
from thzdaq_core.domain.measurements.plots import PlotSpec
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.sis.demagnetization import demagnetization_currents


class Demagnetize(Procedure):
    name = DEMAGNETIZE
    title = "SIS magnet demagnetization"
    description = (
        "Sweep the coil current over the full range, then swing it around the "
        "centre with a shrinking amplitude and leave it at the centre."
    )
    requires = {"coil": CurrentSource}
    plots = (
        PlotSpec(
            "coil", "Coil current", "coil", "step", "current",
            x_label="Step", y_label="Current, mA", y_scale=MA,
        ),
    )  # fmt: skip

    minimum = FloatParameter(
        "Minimum current",
        default=-30 * MA,
        unit="A",
        display_unit="mA",
        display_scale=MA,
    )
    maximum = FloatParameter(
        "Maximum current",
        default=30 * MA,
        unit="A",
        display_unit="mA",
        display_scale=MA,
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
    name = CL_CURVE
    title = "SIS I-CL curve"
    description = (
        "Sweep the magnet coil current and read the bias current: finds the "
        "coil current that suppresses the Josephson current."
    )
    requires = {"coil": CurrentSource, "bias": VoltageCurrentMeter}
    plots = (
        PlotSpec(
            "cl", "I-CL", "cl", "coil_current", "current",
            x_label=COIL_CURRENT_MA, y_label=CURRENT_UA,
            x_scale=MA, y_scale=UA,
        ),
    )  # fmt: skip

    coil_current = SweepParameter(
        "Coil current",
        default=(0.0, 30e-3, 61),
        unit="A",
        display_unit="mA",
        display_scale=MA,
    )
    step_delay = FloatParameter("Step delay", default=0.1, minimum=0, unit="s")

    def estimate_steps(self) -> int:
        return self.coil_current.points

    def run(self, ctx) -> None:
        coil, bias = ctx["coil"], ctx["bias"]
        initial = coil.get_current()
        ctx.on_exit(lambda: coil.set_current(initial))
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
