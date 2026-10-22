from itertools import product

from thzdaq_instruments.capabilities import PowerDetector, PowerLevel, TunableFilter
from thzdaq_instruments.units import GHZ, MV, UA

from thzdaq_core.analysis.two_sb import SIDE_BANDS
from thzdaq_core.measurements.parameters import (
    BoolParameter,
    ChoiceParameter,
    FloatListParameter,
    FloatParameter,
    SweepParameter,
)
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedures.common import mv, set_bias
from thzdaq_core.measurements.procedures.two_sb.common import (
    SOURCE,
    TwoSbProcedure,
    if_sweep,
)
from thzdaq_core.measurements.registry import register_procedure
from thzdaq_core.station.ports import SidebandSwitch


@register_procedure
class IfBalance(TwoSbProcedure):
    name = "two_sb.if_balance"
    title = "2SB IF balance"
    description = (
        "IF power of both channels over the IF band for every SIS1 x SIS2 bias pair."
    )
    plots = (
        PlotSpec(
            "power", "P-IF", "power", "frequency", "power",
            x_label="IF, GHz", y_label="Power, dBm", x_scale=GHZ,
            group_by=("channel", "bias"),
        ),
    )  # fmt: skip

    sis1_voltages = FloatListParameter(
        "SIS1 voltages",
        default=(5e-3, 6e-3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    sis2_voltages = FloatListParameter(
        "SIS2 voltages",
        default=(5e-3, 6e-3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    frequency = if_sweep()
    point_delay = FloatParameter("Point delay", default=0.05, minimum=0, unit="s")

    def slots(self):
        return {
            **self.base_slots(),
            "if_selector": SidebandSwitch,
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


@register_procedure
class PumpBalance(TwoSbProcedure):
    name = "two_sb.pump_balance"
    title = "2SB LO/RF balance"
    description = (
        "Pumped currents of both mixers versus LO or RF frequency for paired "
        "SIS1/SIS2 bias points."
    )
    plots = (
        PlotSpec(
            "sis1", "SIS1 I-F", "pump", "frequency", "sis1_current",
            x_label="Frequency, GHz", y_label="Current, μA", x_scale=GHZ, y_scale=UA,
            group_by=("bias",),
        ),
        PlotSpec(
            "sis2", "SIS2 I-F", "pump", "frequency", "sis2_current",
            x_label="Frequency, GHz", y_label="Current, μA", x_scale=GHZ, y_scale=UA,
            group_by=("bias",),
        ),
    )  # fmt: skip

    source = ChoiceParameter(
        "Swept source", ("lo", "test_tone"), default="lo",
        help="lo: LO balance, test_tone: RF balance",
    )  # fmt: skip
    frequency = SweepParameter(
        "Frequency at the mixer", default=(220 * GHZ, 265 * GHZ, 46), unit="Hz",
        display_unit="GHz", display_scale=GHZ,
    )  # fmt: skip
    source_power = FloatParameter("Source power", default=4.0, maximum=25, unit="dBm")
    silence_other = BoolParameter(
        "Silence the other source", default=True,
        help="Output off and -80 dBm on the source that is not swept",
    )  # fmt: skip
    sis1_voltage = SweepParameter(
        "SIS1 bias",
        default=(2.4e-3, 2.6e-3, 3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    sis2_voltage = SweepParameter(
        "SIS2 bias",
        default=(2.4e-3, 2.6e-3, 3),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    bias_delay = FloatParameter("Bias delay", default=0.1, minimum=0, unit="s")
    measure_power = BoolParameter("Read IF power", default=False)
    precise_bias = BoolParameter("Precise bias", default=False)

    @property
    def other(self) -> str:
        return "test_tone" if self.source == "lo" else "lo"

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
