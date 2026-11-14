import cmath
import math

from thzdaq_api.devices import S_DB
from thzdaq_api.leases import EXCLUSIVE
from thzdaq_api.procedures import REFLECTION_VS_FREQUENCY
from thzdaq_instruments.capabilities import NetworkAnalyzer, PowerLevel
from thzdaq_instruments.quantities import POWER_LEVEL
from thzdaq_instruments.units import GHZ, MV

from thzdaq_core.domain.parameters import (
    FloatParameter,
    IntParameter,
    MultiChoiceParameter,
    SweepParameter,
)
from thzdaq_api.measurements import PlotInfo, plot_caption
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.procedures.common import (
    BIAS,
    VOLTAGE_MV,
    BiasVoltage,
    FirstPointDelay,
    Group,
)

S_PARAMETERS = ("S11", "S21", "S12", "S22")


class SisReflection(Procedure):
    name = REFLECTION_VS_FREQUENCY
    slot_modes = {"bias": EXCLUSIVE}
    title = "SIS reflection (VNA)"
    description = "S-parameters of the SIS IF port over a bias sweep."
    guide = (
        "S-parameters of the SIS IF port from the VNA at each bias point: the match "
        "between the junction and the IF chain. Keep the VNA power low (the default "
        "-30 dBm) so the probe does not pump the junction; averages and the wait "
        "after each change trade speed for noise."
    )
    requires = {"bias": BIAS, "vna": (NetworkAnalyzer, PowerLevel)}
    plots = (
        PlotInfo(
            "magnitude", "|S| (band mean) - V", "summary", "voltage", "magnitude_db",
            x_label=VOLTAGE_MV, y_label=S_DB, x_scale=MV, group_by=("parameter",),
            caption=plot_caption("|S|–V", "Reflection, band mean (bias voltage)"),
        ),
    )  # fmt: skip

    voltage = BiasVoltage((0.0, 7e-3, 71))
    frequency = SweepParameter(
        "VNA frequency", default=(2 * GHZ, 12 * GHZ, 301), unit="Hz",
        display_unit="GHz", display_scale=GHZ, group=Group.VNA,
    )  # fmt: skip
    power = FloatParameter(
        "VNA power", default=-30.0, minimum=-100, maximum=10, unit="dBm",
        applies=("vna", POWER_LEVEL.key), group=Group.VNA,
    )  # fmt: skip
    s_parameters = MultiChoiceParameter(
        "S-parameters", S_PARAMETERS, default=("S11",), group=Group.VNA
    )
    averages = IntParameter(
        "VNA averages", default=1, minimum=1, maximum=1000, group=Group.VNA
    )
    samples = IntParameter(
        "Traces per point", default=1, minimum=1, maximum=100, group=Group.VNA
    )
    averaging_time = FloatParameter(
        "Averaging wait", default=0.8, minimum=0, unit="s", group=Group.TIMING,
        help="Wait after changing bias or S-parameter for the VNA to average",
    )  # fmt: skip
    first_point_delay = FirstPointDelay(1.0)

    def estimate_steps(self) -> int:
        return self.voltage.points * len(self.s_parameters) * self.samples

    def run(self, ctx) -> None:
        bias, vna = ctx["bias"], ctx["vna"]
        vna.set_frequency_range(self.frequency.start, self.frequency.stop)
        vna.set_points(self.frequency.points)
        vna.set_power(self.power)
        vna.set_averaging(self.averages)

        for index, voltage_set in enumerate(self.voltage.values()):
            ctx.check_cancel()
            bias.set_voltage(voltage_set)
            if index == 0:
                ctx.sleep(self.first_point_delay)
            reading = bias.measure()
            ctx.record(
                "iv",
                voltage_set=voltage_set,
                voltage=reading.voltage,
                current=reading.current,
            )
            for parameter in self.s_parameters:
                vna.select_parameter(parameter)
                ctx.sleep(self.averaging_time)
                for sample in range(self.samples):
                    trace = vna.read_trace()
                    if "frequency" not in ctx.measurement.results:
                        ctx.result("frequency", list(trace.frequency))
                    ctx.record(
                        "trace",
                        voltage_set=voltage_set,
                        voltage=reading.voltage,
                        parameter=parameter,
                        sample=sample,
                        values=list(trace.values),
                    )
                    mean = sum(abs(v) ** 2 for v in trace.values) / len(trace.values)
                    ctx.record(
                        "summary",
                        voltage=reading.voltage,
                        parameter=parameter,
                        sample=sample,
                        magnitude_db=10 * math.log10(mean) if mean > 0 else -math.inf,
                        phase_mean=cmath.phase(sum(trace.values)),
                    )
                    ctx.progress()
