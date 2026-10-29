from thzdaq_api.procedures import IV_CURVE
from thzdaq_instruments.capabilities import VoltageCurrentMeter, VoltageSource
from thzdaq_instruments.units import MV, UA

from thzdaq_core.domain.measurements.procedures.common import (
    CURRENT_UA,
    VOLTAGE_MV,
    BiasVoltage,
    FirstPointDelay,
    SettleTime,
)
from thzdaq_core.domain.measurements.plots import PlotSpec
from thzdaq_core.domain.measurements.procedure import Procedure


class IVCurve(Procedure):
    name = IV_CURVE
    title = "SIS I-V curve"
    description = "Sweep the bias voltage and read voltage and current."
    requires = {"bias": (VoltageSource, VoltageCurrentMeter)}
    plots = (
        PlotSpec(
            key="iv",
            title="I-V",
            table="iv",
            x="voltage",
            y="current",
            x_label=VOLTAGE_MV,
            y_label=CURRENT_UA,
            x_scale=MV,
            y_scale=UA,
            analysis="iv",
        ),
    )

    voltage = BiasVoltage((0.0, 7e-3, 351))
    settle_time = SettleTime(0.01, maximum=10)
    first_point_delay = FirstPointDelay(0.5, maximum=10)

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
