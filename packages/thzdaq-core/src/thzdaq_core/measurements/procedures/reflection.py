import cmath
import math

from thzdaq_instruments.capabilities import NetworkAnalyzer, PowerLevel
from thzdaq_instruments.units import GHZ, MV

from thzdaq_core.measurements.parameters import (
    FloatParameter,
    IntParameter,
    MultiChoiceParameter,
    SweepParameter,
)
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import BIAS, restore_bias_on_exit
from thzdaq_core.measurements.registry import register_procedure

S_PARAMETERS = ("S11", "S21", "S12", "S22")


@register_procedure
class SisReflection(Procedure):
    name = "sis.reflection"
    title = "SIS reflection (VNA)"
    description = "S-parameters of the SIS IF port over a bias sweep."
    requires = {"bias": BIAS, "vna": (NetworkAnalyzer, PowerLevel)}
    plots = (
        PlotSpec(
            "magnitude", "|S| (band mean) - V", "summary", "voltage", "magnitude_db",
            x_label="Voltage, mV", y_label="|S|, dB", x_scale=MV, group_by=("parameter",),
        ),
    )  # fmt: skip

    voltage = SweepParameter(
        "Bias voltage",
        default=(0.0, 7e-3, 71),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    frequency = SweepParameter(
        "VNA frequency", default=(2 * GHZ, 12 * GHZ, 301), unit="Hz",
        display_unit="GHz", display_scale=GHZ,
    )  # fmt: skip
    power = FloatParameter(
        "VNA power", default=-30.0, minimum=-100, maximum=10, unit="dBm"
    )
    s_parameters = MultiChoiceParameter("S-parameters", S_PARAMETERS, default=("S11",))
    averages = IntParameter("VNA averages", default=1, minimum=1, maximum=1000)
    samples = IntParameter("Traces per point", default=1, minimum=1, maximum=100)
    averaging_time = FloatParameter(
        "Averaging wait", default=0.8, minimum=0, unit="s",
        help="Wait after changing bias or S-parameter for the VNA to average",
    )  # fmt: skip
    first_point_delay = FloatParameter(
        "First point delay", default=1.0, minimum=0, unit="s"
    )

    def estimate_steps(self) -> int:
        return self.voltage.points * len(self.s_parameters) * self.samples

    def run(self, ctx) -> None:
        bias, vna = ctx["bias"], ctx["vna"]
        restore_bias_on_exit(ctx, bias)
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
