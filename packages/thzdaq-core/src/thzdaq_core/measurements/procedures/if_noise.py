from thzdaq_instruments.capabilities import LoadSwitch, PowerDetector, TunableFilter
from thzdaq_instruments.units import GHZ

from thzdaq_core.analysis.noise import noise_temperature, y_factor_db
from thzdaq_core.measurements.parameters import FloatParameter, SweepParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import warn_without_contrast
from thzdaq_core.measurements.registry import register_procedure

LOADS = ("cold", "hot")


@register_procedure
class IFNoise(Procedure):
    name = "if.hot_cold"
    title = "IF noise (hot/cold)"
    description = (
        "Sweep the IF filter with the cold and the hot load and compute the "
        "Y-factor and the receiver noise temperature."
    )
    requires = {
        "detector": PowerDetector,
        "if_filter": TunableFilter,
        "load": LoadSwitch,
    }
    plots = (
        PlotSpec(
            key="power",
            title="P-IF",
            table="power",
            x="frequency",
            y="power",
            x_label="IF, GHz",
            y_label="Power, dBm",
            x_scale=GHZ,
            group_by=("load",),
        ),
        PlotSpec(
            key="y_factor",
            title="Y-IF",
            table="noise",
            x="frequency",
            y="y_factor",
            x_label="IF, GHz",
            y_label="Y, dB",
            x_scale=GHZ,
        ),
        PlotSpec(
            key="tn",
            title="Tn-IF",
            table="noise",
            x="frequency",
            y="noise_temperature",
            x_label="IF, GHz",
            y_label="Tn, K",
            x_scale=GHZ,
        ),
    )

    frequency = SweepParameter(
        "IF",
        default=(4 * GHZ, 12 * GHZ, 201),
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
    )
    t_hot = FloatParameter("Hot load", default=300.0, minimum=0, unit="K")
    t_cold = FloatParameter("Cold load", default=77.0, minimum=0, unit="K")
    load_delay = FloatParameter("Load switch delay", default=0.5, minimum=0, unit="s")
    point_delay = FloatParameter("Point delay", default=0.01, minimum=0, unit="s")

    def check(self):
        if self.t_hot <= self.t_cold:
            return ["hot load must be warmer than the cold one"]
        return []

    def estimate_steps(self) -> int:
        return len(LOADS) * self.frequency.points

    def run(self, ctx) -> None:
        detector, if_filter, load = ctx["detector"], ctx["if_filter"], ctx["load"]
        ctx.on_exit(load.to_cold)
        powers = {}
        for state in LOADS:
            ctx.check_cancel()
            getattr(load, f"to_{state}")()
            ctx.sleep(self.load_delay)
            for frequency in self.frequency.values():
                actual = if_filter.tune(frequency)
                ctx.sleep(self.point_delay)
                power = detector.read_power()
                powers[state, frequency] = power
                ctx.record(
                    "power",
                    frequency=actual,
                    frequency_set=frequency,
                    load=state,
                    power=power,
                )
                ctx.progress()
        temperatures = []
        for frequency in self.frequency.values():
            hot, cold = powers["hot", frequency], powers["cold", frequency]
            tn = noise_temperature(hot, cold, self.t_hot, self.t_cold)
            temperatures.append(tn)
            ctx.record(
                "noise",
                frequency=frequency,
                y_factor=y_factor_db(hot, cold),
                noise_temperature=tn,
            )
        warn_without_contrast(ctx, temperatures, "IF noise")
