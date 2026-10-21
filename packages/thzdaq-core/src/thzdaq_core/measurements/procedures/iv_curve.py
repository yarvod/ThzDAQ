from thzdaq_instruments.capabilities import VoltageCurrentMeter, VoltageSource
from thzdaq_instruments.units import MV, UA

from thzdaq_core.measurements.parameters import FloatParameter, SweepParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.registry import register_procedure


@register_procedure
class IVCurve(Procedure):
    name = "sis.iv_curve"
    title = "SIS I-V curve"
    description = "Sweep the bias voltage and read voltage and current."
    requires = {"bias": (VoltageSource, VoltageCurrentMeter)}
    plots = (
        PlotSpec(
            key="iv",
            title="I-V",
            stream="iv",
            x="voltage",
            y="current",
            x_label="Voltage, mV",
            y_label="Current, μA",
            x_scale=MV,
            y_scale=UA,
        ),
    )

    voltage = SweepParameter(
        "Bias voltage",
        default=(0.0, 7e-3, 351),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    settle_time = FloatParameter(
        "Settle time", default=0.01, minimum=0, maximum=10, unit="s"
    )
    first_point_delay = FloatParameter(
        "First point delay",
        default=0.5,
        minimum=0,
        maximum=10,
        unit="s",
        help="The bias source needs longer to reach the first point",
    )

    def estimate_steps(self) -> int:
        return self.voltage.points

    def run(self, ctx) -> None:
        bias = ctx["bias"]
        initial = bias.get_voltage()
        ctx.on_exit(lambda: bias.set_voltage(initial))
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
