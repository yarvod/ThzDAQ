from itertools import product

from thzdaq_api.devices import POWER_DBM
from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import TWO_SB_IF_BALANCE, TWO_SB_LO_RF_BALANCE
from thzdaq_instruments.capabilities import (
    PowerDetector,
    PowerLevel,
    Switchable,
    TunableFilter,
)
from thzdaq_instruments.quantities import VOLTAGE_SET
from thzdaq_instruments.units import GHZ, MV, UA

from thzdaq_analysis.two_sb import SIDE_BANDS
from thzdaq_core.domain.parameters import (
    BoolParameter,
    ChoiceParameter,
    FloatListParameter,
    FloatParameter,
    SweepParameter,
)
from thzdaq_api.measurements import PlotInfo, plot_caption
from thzdaq_core.domain.measurements.procedures.common import (
    P_IF_CAPTION,
    Group,
    CURRENT_UA,
    FREQUENCY_GHZ,
    IF_GHZ,
    IFSweep,
    mv,
    PointDelay,
    set_bias,
)
from thzdaq_core.domain.measurements.procedures.two_sb.common import (
    SOURCE,
    IfSwitchProcedure,
    PreciseBias,
    SisBiasSweep,
    TwoSbProcedure,
)


class IfBalance(IfSwitchProcedure):
    name = TWO_SB_IF_BALANCE
    slot_modes = {
        "sis1": EXCLUSIVE,
        "sis2": EXCLUSIVE,
        "if_filter": EXCLUSIVE,
        "detector": READ,
    }
    title = "2SB IF balance"
    description = (
        "IF power of both channels over the IF band for every SIS1 x SIS2 bias pair."
    )
    guide = (
        "The IF power of the upper and the lower channel over the band for every "
        "SIS1 x SIS2 bias pair: how evenly the two mixers of the 2SB pair give "
        "power. Pump both mixers first. List a few bias values of each (the steps "
        "of both mixers' I-V); the run takes every pair, so keep the lists short."
    )
    plots = (
        PlotInfo(
            "power", "P-IF", "power", "frequency", "power",
            x_label=IF_GHZ, y_label=POWER_DBM, x_scale=GHZ,
            group_by=("channel", "bias"),
            caption=P_IF_CAPTION,
        ),
    )  # fmt: skip

    sis1_voltages = FloatListParameter(
        "SIS1 voltages",
        default=(5e-3, 6e-3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
        applies=("sis1", VOLTAGE_SET.key),
        group=Group.BIAS,
    )
    sis2_voltages = FloatListParameter(
        "SIS2 voltages",
        default=(5e-3, 6e-3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
        applies=("sis2", VOLTAGE_SET.key),
        group=Group.BIAS,
    )
    frequency = IFSweep()
    point_delay = PointDelay(0.05)

    def slots(self):
        return {
            **self.base_slots(),
            "if_selector": Switchable,
            "detector": PowerDetector,
            "if_filter": TunableFilter,
        }

    def estimate_steps(self) -> int:
        pairs = len(self.sis1_voltages) * len(self.sis2_voltages)
        return pairs * len(SIDE_BANDS) * self.frequency.points

    def run(self, ctx) -> None:
        self.start(ctx)
        detector, if_filter = ctx["detector"], ctx["if_filter"]
        for v1, v2 in product(self.sis1_voltages, self.sis2_voltages):
            ctx.check_cancel()
            self.bias(ctx, v1, v2)
            label = f"{v1 * 1e3:.2f}/{v2 * 1e3:.2f} mV"
            ctx.record(
                "bias",
                bias=label,
                sis1_voltage_set=v1,
                sis2_voltage_set=v2,
                **self.read_bias(ctx),
            )
            for side_band in SIDE_BANDS:
                self.select_channel(ctx, side_band, self.switch_delay)
                for frequency in self.frequency.values():
                    ctx.check_cancel()
                    actual = if_filter.tune(frequency)
                    ctx.sleep(self.point_delay)
                    ctx.record(
                        "power",
                        bias=label,
                        sis1_voltage_set=v1,
                        sis2_voltage_set=v2,
                        channel=side_band,
                        frequency=actual,
                        power=detector.read_power(),
                    )
                    ctx.progress()


class PumpBalance(TwoSbProcedure):
    name = TWO_SB_LO_RF_BALANCE
    slot_modes = {"sis1": EXCLUSIVE, "sis2": EXCLUSIVE, "detector": READ}
    title = "2SB LO/RF balance"
    description = (
        "Pumped currents of both mixers versus LO or RF frequency for paired "
        "SIS1/SIS2 bias points."
    )
    guide = (
        "How evenly the LO (or the RF test tone) pumps the two mixers of the 2SB "
        "pair over frequency: both SIS currents at paired bias points while the "
        "source sweeps. Keep the source power within its limits; silence_other "
        "turns the other source off so it does not pump them too."
    )
    plots = (
        PlotInfo(
            "sis1", "SIS1 I-F", "pump", "frequency", "sis1_current",
            x_label=FREQUENCY_GHZ, y_label=CURRENT_UA, x_scale=GHZ, y_scale=UA,
            group_by=("bias",),
            caption=plot_caption("I–f", "SIS1 current (LO frequency)"),
        ),
        PlotInfo(
            "sis2", "SIS2 I-F", "pump", "frequency", "sis2_current",
            x_label=FREQUENCY_GHZ, y_label=CURRENT_UA, x_scale=GHZ, y_scale=UA,
            group_by=("bias",),
            caption=plot_caption("I–f", "SIS2 current (LO frequency)"),
        ),
    )  # fmt: skip

    source = ChoiceParameter(
        "Swept source", ("lo", "test_tone"), default="lo", group=Group.SOURCE,
        help="lo: LO balance, test_tone: RF balance",
    )  # fmt: skip
    frequency = SweepParameter(
        "Frequency at the mixer", default=(220 * GHZ, 265 * GHZ, 46), unit="Hz",
        display_unit="GHz", display_scale=GHZ, group=Group.SOURCE,
    )  # fmt: skip
    source_power = FloatParameter(
        "Source power", default=4.0, maximum=25, unit="dBm", group=Group.SOURCE
    )
    silence_other = BoolParameter(
        "Silence the other source", default=True, group=Group.SOURCE,
        help="Output off and -80 dBm on the source that is not swept",
    )  # fmt: skip
    sis1_voltage = SisBiasSweep(1, (2.4e-3, 2.6e-3, 3))
    sis2_voltage = SisBiasSweep(2, (2.4e-3, 2.6e-3, 3))
    bias_delay = FloatParameter(
        "Bias delay", default=0.1, minimum=0, unit="s", group=Group.TIMING
    )
    measure_power = BoolParameter("Read IF power", default=False, group=Group.DETECTOR)
    precise_bias = PreciseBias(False)

    @property
    def other(self) -> str:
        return "test_tone" if self.source == "lo" else "lo"

    def slot_mode(self, slot: str) -> str:
        return EXCLUSIVE if slot == self.source else super().slot_mode(slot)

    def slots(self):
        slots = {**self.base_slots(), self.source: SOURCE + (PowerLevel,)}
        if self.silence_other:
            slots[self.other] = SOURCE + (PowerLevel,)
        if self.measure_power:
            slots["detector"] = PowerDetector
        return slots

    def check(self):
        if self.sis1_voltage.points != self.sis2_voltage.points:
            return ["SIS1 and SIS2 sweeps need the same number of points"]
        return []

    def estimate_steps(self) -> int:
        return self.frequency.points * self.sis1_voltage.points

    def run(self, ctx) -> None:
        self.start(ctx)
        source = ctx[self.source]
        if self.silence_other:
            other = ctx[self.other]
            other.set_power(-80)
            other.set_output(False)
        source.set_power(self.source_power)
        source.set_output(True)
        if self.source == "test_tone":
            ctx.on_exit(lambda: source.set_output(False))
        pairs = list(zip(self.sis1_voltage.values(), self.sis2_voltage.values()))
        for frequency in self.frequency.values():
            ctx.check_cancel()
            source.set_frequency(frequency)
            for v1, v2 in pairs:
                ctx.check_cancel()
                set_bias(ctx["sis2"], v2, self.precise_bias)
                set_bias(ctx["sis1"], v1, self.precise_bias)
                ctx.sleep(self.bias_delay)
                record = {
                    "bias": f"{mv(v1)}/{mv(v2)}",
                    "frequency": frequency,
                    "sis1_voltage_set": v1,
                    "sis2_voltage_set": v2,
                    **self.read_bias(ctx),
                }
                if self.measure_power:
                    record["power"] = ctx["detector"].read_power()
                ctx.record("pump", **record)
                ctx.progress()
