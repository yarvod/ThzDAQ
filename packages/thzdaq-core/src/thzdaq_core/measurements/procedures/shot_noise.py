from thzdaq_instruments.capabilities import PowerDetector, TunableFilter
from thzdaq_instruments.readings import linspace
from thzdaq_instruments.units import GHZ, MV, dbm_to_watt

from thzdaq_core.analysis.shot_noise import (
    amplifier_temperature,
    dynamic_resistance,
    mismatch,
    shot_noise_temperature,
)
from thzdaq_core.measurements.parameters import (
    FloatParameter,
    IntParameter,
    SweepParameter,
)
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import BIAS, restore_bias_on_exit
from thzdaq_core.measurements.registry import register_procedure


@register_procedure
class ShotNoise(Procedure):
    name = "sis.shot_noise"
    title = "IF amplifier noise (SIS shot noise)"
    description = (
        "At two bias points above the gap: fit the dynamic resistance, sweep "
        "the IF power and compute the IF amplifier noise temperature."
    )
    requires = {"bias": BIAS, "detector": PowerDetector, "if_filter": TunableFilter}
    plots = (
        PlotSpec(
            "power", "P-IF", "power", "frequency", "power",
            x_label="IF, GHz", y_label="Power, dBm", x_scale=GHZ, group_by=("point",),
        ),
        PlotSpec(
            "ta", "Ta-IF", "noise", "frequency", "amplifier_temperature",
            x_label="IF, GHz", y_label="Ta, K", x_scale=GHZ,
        ),
    )  # fmt: skip

    voltage1 = FloatParameter(
        "Bias 1", default=15e-3, unit="V", display_unit="mV", display_scale=MV
    )
    voltage2 = FloatParameter(
        "Bias 2", default=20e-3, unit="V", display_unit="mV", display_scale=MV
    )
    resistance_span = FloatParameter(
        "Rd fit span", default=0.05, minimum=0.001, maximum=0.5,
        help="Relative half-width of the bias sweep around each point",
    )  # fmt: skip
    resistance_points = IntParameter(
        "Rd fit points", default=100, minimum=3, maximum=10000
    )
    frequency = SweepParameter(
        "IF",
        default=(3 * GHZ, 13 * GHZ, 300),
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
    )
    t_sis = FloatParameter("SIS temperature", default=4.0, minimum=0.1, unit="K")
    settle_time = FloatParameter("Settle time", default=0.05, minimum=0, unit="s")
    point_delay = FloatParameter("IF point delay", default=0.01, minimum=0, unit="s")

    def check(self):
        if self.voltage1 == self.voltage2:
            return ["bias points must differ"]
        return []

    def estimate_steps(self) -> int:
        return 2 * (self.resistance_points + self.frequency.points)

    def run(self, ctx) -> None:
        bias, detector, if_filter = ctx["bias"], ctx["detector"], ctx["if_filter"]
        restore_bias_on_exit(ctx, bias)
        points = {}
        for point, voltage in ((1, self.voltage1), (2, self.voltage2)):
            points[point] = self._bias_point(ctx, bias, point, voltage)
        for point, voltage in ((1, self.voltage1), (2, self.voltage2)):
            bias.set_voltage(voltage)
            ctx.sleep(self.settle_time * 10)
            reading = bias.measure()
            points[point]["voltage"] = reading.voltage
            points[point]["current"] = reading.current
            powers = []
            for frequency in self.frequency.values():
                ctx.check_cancel()
                actual = if_filter.tune(frequency)
                ctx.sleep(self.point_delay)
                power = detector.read_power()
                powers.append(power)
                ctx.record("power", point=point, frequency=actual, power=power)
                ctx.progress()
            points[point]["powers"] = powers

        one, two = points[1], points[2]
        t1 = shot_noise_temperature(
            one["current"], one["voltage"], one["rd"], self.t_sis
        )
        t2 = shot_noise_temperature(
            two["current"], two["voltage"], two["rd"], self.t_sis
        )
        m1, m2 = mismatch(one["rd"]), mismatch(two["rd"])
        for index, frequency in enumerate(self.frequency.values()):
            ctx.record(
                "noise",
                frequency=frequency,
                amplifier_temperature=amplifier_temperature(
                    dbm_to_watt(one["powers"][index]),
                    dbm_to_watt(two["powers"][index]),
                    t1,
                    t2,
                    m1,
                    m2,
                ),
            )
        for point, data in points.items():
            ctx.result(f"rd{point}", data["rd"])
            ctx.result(f"voltage{point}", data["voltage"])
            ctx.result(f"current{point}", data["current"])

    def _bias_point(self, ctx, bias, point: int, voltage: float):
        span = abs(voltage) * self.resistance_span
        voltages, currents = [], []
        for voltage_set in linspace(
            voltage - span, voltage + span, self.resistance_points
        ):
            ctx.check_cancel()
            bias.set_voltage(voltage_set)
            ctx.sleep(self.settle_time)
            reading = bias.measure()
            voltages.append(reading.voltage)
            currents.append(reading.current)
            ctx.record(
                "resistance",
                point=point,
                voltage=reading.voltage,
                current=reading.current,
            )
            ctx.progress()
        rd = dynamic_resistance(voltages, currents)
        ctx.log(f"point {point}: Rd = {rd:.2f} Ohm")
        return {"rd": rd}
