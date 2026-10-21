from thzdaq_instruments.capabilities import CurrentSource
from thzdaq_instruments.units import MA

from thzdaq_core.measurements.parameters import FloatParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.registry import register_procedure
from thzdaq_core.sis.demagnetization import demagnetization_currents


@register_procedure
class Demagnetize(Procedure):
    name = "sis.demagnetize"
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
