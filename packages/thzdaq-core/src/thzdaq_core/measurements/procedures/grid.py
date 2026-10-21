from thzdaq_instruments.capabilities import Rotator, VoltageCurrentMeter
from thzdaq_instruments.units import UA

from thzdaq_core.measurements.parameters import FloatParameter, SweepParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import restore_angle_on_exit
from thzdaq_core.measurements.registry import register_procedure


@register_procedure
class GridCurrentAngle(Procedure):
    name = "grid.current_angle"
    title = "SIS current versus grid angle"
    description = "Rotate the wire grid and read the pumped SIS current (I-A curve)."
    requires = {"grid": Rotator, "bias": VoltageCurrentMeter}
    plots = (
        PlotSpec(
            "ia", "I-A", "ia", "angle", "current",
            x_label="Angle, deg", y_label="Current, μA", y_scale=UA,
        ),
    )  # fmt: skip

    angle = SweepParameter(
        "Grid angle", default=(0.0, 180.0, 37), unit="deg", max_points=10000
    )
    grid_speed = FloatParameter(
        "Grid speed", default=180.0, minimum=1e-3, unit="deg/s",
        help="Wait |Δangle| / speed after each rotation",
    )  # fmt: skip
    settle_time = FloatParameter("Settle time", default=0.1, minimum=0, unit="s")

    def estimate_steps(self) -> int:
        return self.angle.points

    def run(self, ctx) -> None:
        grid, bias = ctx["grid"], ctx["bias"]
        restore_angle_on_exit(ctx, grid)
        for angle in self.angle.values():
            ctx.check_cancel()
            travel = abs(angle - grid.get_angle())
            reached = grid.rotate_to(angle)
            ctx.sleep(travel / self.grid_speed + self.settle_time)
            reading = bias.measure()
            ctx.record(
                "ia", angle=reached, voltage=reading.voltage, current=reading.current
            )
            ctx.progress()
