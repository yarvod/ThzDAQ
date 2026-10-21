from thzdaq_instruments.capabilities import LoadSwitch, PowerDetector, Rotator
from thzdaq_instruments.units import MV, UA

from thzdaq_core.analysis.noise import match_hot_cold, noise_temperature
from thzdaq_core.measurements.parameters import (
    BoolParameter,
    FloatParameter,
    IntParameter,
    SweepParameter,
)
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import (
    BIAS,
    restore_angle_on_exit,
    restore_bias_on_exit,
)
from thzdaq_core.measurements.registry import register_procedure


@register_procedure
class PVCurve(Procedure):
    name = "sis.pv_curve"
    title = "SIS P-V curve"
    description = (
        "Sweep the bias and read the IF power; optionally with hot and cold "
        "loads (Y-factor and Tn versus voltage) and at several grid angles."
    )
    requires = {"bias": BIAS, "detector": PowerDetector}
    plots = (
        PlotSpec(
            "pv", "P-V", "pv", "voltage", "power",
            x_label="Voltage, mV", y_label="Power, dBm", x_scale=MV,
            group_by=("angle", "load"),
        ),
        PlotSpec(
            "iv", "I-V", "pv", "voltage", "current",
            x_label="Voltage, mV", y_label="Current, μA", x_scale=MV, y_scale=UA,
            group_by=("angle", "load"), analysis="iv",
        ),
        PlotSpec(
            "y_factor", "Y-V", "y_factor", "voltage", "y_factor",
            x_label="Voltage, mV", y_label="Y, dB", x_scale=MV, group_by=("angle",),
        ),
        PlotSpec(
            "tn", "Tn-V", "y_factor", "voltage", "noise_temperature",
            x_label="Voltage, mV", y_label="Tn, K", x_scale=MV, group_by=("angle",),
        ),
    )  # fmt: skip

    voltage = SweepParameter(
        "Bias voltage",
        default=(0.0, 7e-3, 351),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    settle_time = FloatParameter("Settle time", default=0.01, minimum=0, unit="s")
    first_point_delay = FloatParameter(
        "First point delay", default=0.5, minimum=0, unit="s"
    )
    hot_cold = BoolParameter("Hot/cold loads", default=False)
    load_delay = FloatParameter("Load switch delay", default=2.0, minimum=0, unit="s")
    t_hot = FloatParameter("Hot load", default=300.0, minimum=0, unit="K")
    t_cold = FloatParameter("Cold load", default=77.0, minimum=0, unit="K")
    match_window = IntParameter(
        "Hot/cold match window", default=10, minimum=1,
        help="Cold points around the same index searched for the nearest voltage",
    )  # fmt: skip
    use_grid = BoolParameter("Rotate grid", default=False)
    angle = SweepParameter(
        "Grid angle", default=(0.0, 90.0, 10), unit="deg", max_points=1000
    )
    grid_speed = FloatParameter(
        "Grid speed", default=180.0, minimum=1e-3, unit="deg/s",
        help="Wait |Δangle| / speed after each rotation",
    )  # fmt: skip

    def roles(self):
        roles = dict(self.requires)
        if self.hot_cold:
            roles["load"] = LoadSwitch
        if self.use_grid:
            roles["grid"] = Rotator
        return roles

    def check(self):
        if self.hot_cold and self.t_hot <= self.t_cold:
            return ["hot load must be warmer than the cold one"]
        return []

    def _angles(self):
        return self.angle.values() if self.use_grid else [None]

    def estimate_steps(self) -> int:
        loads = 2 if self.hot_cold else 1
        return len(self._angles()) * loads * self.voltage.points

    def run(self, ctx) -> None:
        bias, detector = ctx["bias"], ctx["detector"]
        restore_bias_on_exit(ctx, bias)
        load = ctx["load"] if self.hot_cold else None
        grid = ctx["grid"] if self.use_grid else None
        if load is not None:
            ctx.on_exit(load.to_cold)
        if grid is not None:
            restore_angle_on_exit(ctx, grid)

        for angle in self._angles():
            if grid is not None:
                travel = abs(angle - grid.get_angle())
                grid.rotate_to(angle)
                ctx.sleep(travel / self.grid_speed)
            sweeps = {}
            for state in ("hot", "cold") if load is not None else (None,):
                if state is not None:
                    getattr(load, f"to_{state}")()
                    ctx.sleep(self.load_delay)
                sweeps[state] = self._sweep(ctx, bias, detector, angle, state)
            if load is not None:
                for voltage, hot, cold in match_hot_cold(
                    sweeps["hot"], sweeps["cold"], self.match_window
                ):
                    ctx.record(
                        "y_factor",
                        angle=angle,
                        voltage=voltage,
                        y_factor=hot - cold,
                        noise_temperature=noise_temperature(
                            hot, cold, self.t_hot, self.t_cold
                        ),
                    )

    def _sweep(self, ctx, bias, detector, angle, load):
        points = []
        for index, voltage_set in enumerate(self.voltage.values()):
            ctx.check_cancel()
            bias.set_voltage(voltage_set)
            ctx.sleep(self.first_point_delay if index == 0 else self.settle_time)
            reading = bias.measure()
            power = detector.read_power()
            ctx.record(
                "pv",
                angle=angle,
                load=load,
                voltage_set=voltage_set,
                voltage=reading.voltage,
                current=reading.current,
                power=power,
            )
            points.append((reading.voltage, power))
            ctx.progress()
        return points


@register_procedure
class YFactorVoltage(PVCurve):
    name = "sis.y_factor_voltage"
    title = "SIS Y-factor (V)"
    description = (
        "P-V with hot and cold loads: Y-factor and noise temperature versus bias."
    )
    hot_cold = BoolParameter("Hot/cold loads", default=True)
