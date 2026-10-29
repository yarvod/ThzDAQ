from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import IF_HOT_COLD
from thzdaq_instruments.capabilities import LoadSwitch, PowerDetector, TunableFilter
from thzdaq_instruments.units import GHZ

from thzdaq_analysis.noise import noise_temperature, y_factor_db
from thzdaq_core.domain.measurements.plots import PlotSpec
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.procedures.common import (
    IF_GHZ,
    POWER_DBM,
    TN_K,
    Y_DB,
    ColdLoad,
    HotLoad,
    IFSweep,
    load_problems,
    LoadDelay,
    PointDelay,
    warn_without_contrast,
)

LOADS = ("cold", "hot")


class IFNoise(Procedure):
    name = IF_HOT_COLD
    slot_modes = {"if_filter": EXCLUSIVE, "detector": READ}
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
            x_label=IF_GHZ,
            y_label=POWER_DBM,
            x_scale=GHZ,
            group_by=("load",),
        ),
        PlotSpec(
            key="y_factor",
            title="Y-IF",
            table="noise",
            x="frequency",
            y="y_factor",
            x_label=IF_GHZ,
            y_label=Y_DB,
            x_scale=GHZ,
        ),
        PlotSpec(
            key="tn",
            title="Tn-IF",
            table="noise",
            x="frequency",
            y="noise_temperature",
            x_label=IF_GHZ,
            y_label=TN_K,
            x_scale=GHZ,
        ),
    )

    frequency = IFSweep((4 * GHZ, 12 * GHZ, 201))
    t_hot = HotLoad()
    t_cold = ColdLoad()
    load_delay = LoadDelay(0.5)
    point_delay = PointDelay(0.01)

    def check(self):
        return load_problems(self.t_hot, self.t_cold)

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
