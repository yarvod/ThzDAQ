from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import CURRENT_VS_GRID_ANGLE
from thzdaq_instruments.capabilities import Rotator, VoltageCurrentMeter
from thzdaq_instruments.units import UA

from thzdaq_api.measurements import PlotInfo, plot_caption
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.procedures.common import (
    CURRENT_UA,
    GridAngle,
    GridSpeed,
    restore_angle_on_exit,
    SettleTime,
)


class GridCurrentAngle(Procedure):
    name = CURRENT_VS_GRID_ANGLE
    slot_modes = {"grid": EXCLUSIVE, "bias": READ}
    title = "SIS I-angle (grid)"
    description = "Rotate the wire grid and read the pumped SIS current (I-A curve)."
    requires = {"grid": Rotator, "bias": VoltageCurrentMeter}
    plots = (
        PlotInfo(
            "ia", "I-A", "ia", "angle", "current",
            x_label="Angle, deg", y_label=CURRENT_UA, y_scale=UA,
            caption=plot_caption("I–A", "SIS current (grid angle)"),
        ),
    )  # fmt: skip

    angle = GridAngle((0.0, 180.0, 37), max_points=10000)
    grid_speed = GridSpeed()
    settle_time = SettleTime(0.1)

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
