from thzdaq_api.devices import POWER_DBM
from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import NOISE_TEMPERATURE_VS_FREQUENCY, POWER_VS_FREQUENCY
from thzdaq_instruments.capabilities import LoadSwitch, PowerDetector, TunableFilter
from thzdaq_instruments.units import GHZ

from thzdaq_analysis.noise import noise_temperature, y_factor_db
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.procedures.common import (
    IF_GHZ,
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


def power_plot(group_by=()) -> PlotInfo:
    return PlotInfo(
        key="power",
        title="P-IF",
        table="power",
        x="frequency",
        y="power",
        x_label=IF_GHZ,
        y_label=POWER_DBM,
        x_scale=GHZ,
        group_by=group_by,
    )


class IFScan(Procedure):
    """The IF band through the YIG filter: the power at each frequency."""

    slot_modes = {"if_filter": EXCLUSIVE, "detector": READ}
    requires = {"detector": PowerDetector, "if_filter": TunableFilter}

    frequency = IFSweep((4 * GHZ, 12 * GHZ, 201))
    point_delay = PointDelay(0.01)

    def scan(self, ctx, **labels) -> dict:
        """Power by the frequency set; labels (load) go into every record."""
        detector, if_filter = ctx["detector"], ctx["if_filter"]
        powers = {}
        for frequency in self.frequency.values():
            ctx.check_cancel()
            actual = if_filter.tune(frequency)
            ctx.sleep(self.point_delay)
            power = detector.read_power()
            powers[frequency] = power
            ctx.record(
                "power",
                frequency=actual,
                frequency_set=frequency,
                **labels,
                power=power,
            )
            ctx.progress()
        return powers


class PowerIF(IFScan):
    name = POWER_VS_FREQUENCY
    title = "Power-IF YIG"
    description = "Sweep the YIG filter over the IF band and read the IF power."
    plots = (power_plot(),)

    def estimate_steps(self) -> int:
        return self.frequency.points

    def run(self, ctx) -> None:
        self.scan(ctx)


class IFNoise(IFScan):
    name = NOISE_TEMPERATURE_VS_FREQUENCY
    title = "SIS Tn-IF"
    description = (
        "Sweep the IF filter with the cold and the hot load and compute the "
        "Y-factor and the receiver noise temperature."
    )
    requires = {**IFScan.requires, "load": LoadSwitch}
    plots = (
        power_plot(("load",)),
        PlotInfo(
            key="y_factor",
            title="Y-IF",
            table="noise",
            x="frequency",
            y="y_factor",
            x_label=IF_GHZ,
            y_label=Y_DB,
            x_scale=GHZ,
        ),
        PlotInfo(
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

    t_hot = HotLoad()
    t_cold = ColdLoad()
    load_delay = LoadDelay(0.5)

    def check(self):
        return load_problems(self.t_hot, self.t_cold)

    def estimate_steps(self) -> int:
        return len(LOADS) * self.frequency.points

    def run(self, ctx) -> None:
        load = ctx["load"]
        ctx.on_exit(load.to_cold)
        powers = {}
        for state in LOADS:
            ctx.check_cancel()
            getattr(load, f"to_{state}")()
            ctx.sleep(self.load_delay)
            powers[state] = self.scan(ctx, load=state)
        temperatures = []
        for frequency in self.frequency.values():
            hot, cold = powers["hot"][frequency], powers["cold"][frequency]
            tn = noise_temperature(hot, cold, self.t_hot, self.t_cold)
            temperatures.append(tn)
            ctx.record(
                "noise",
                frequency=frequency,
                y_factor=y_factor_db(hot, cold),
                noise_temperature=tn,
            )
        warn_without_contrast(ctx, temperatures, "IF noise")
