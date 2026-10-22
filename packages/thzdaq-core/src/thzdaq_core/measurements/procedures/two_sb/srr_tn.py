from thzdaq_instruments.capabilities import Switchable
from thzdaq_instruments.units import GHZ

from thzdaq_core.analysis.two_sb import (
    SIDE_BANDS,
    power_difference,
    test_tone_frequency,
)
from thzdaq_core.measurements.parameters import (
    BoolParameter,
    ChoiceParameter,
    FloatParameter,
    IntParameter,
)
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedures.two_sb.common import (
    SIDE_BAND_CHOICES,
    SOURCE,
    HotColdMixin,
    LoMixin,
    SpectrumMixin,
    TwoSbProcedure,
    if_sweep,
    side_bands,
    voltage_parameter,
)
from thzdaq_core.measurements.registry import register_procedure

NOISE_PLOTS = (
    PlotSpec(
        "noise_power", "P-IF hot/cold", "power", "frequency", "power",
        x_label="IF, GHz", y_label="Power, dBm", x_scale=GHZ, group_by=("channel", "load"),
    ),
    PlotSpec(
        "y_factor", "Y-IF", "noise", "frequency", "y_factor",
        x_label="IF, GHz", y_label="Y, dB", x_scale=GHZ, group_by=("channel",),
    ),
    PlotSpec(
        "tn", "Tn-IF", "noise", "frequency", "noise_temperature",
        x_label="IF, GHz", y_label="Tn, K", x_scale=GHZ, group_by=("channel",),
    ),
)  # fmt: skip


@register_procedure
class SidebandRatio(LoMixin, SpectrumMixin, HotColdMixin, TwoSbProcedure):
    name = "two_sb.srr"
    title = "2SB sideband ratio"
    description = (
        "Test tone in each sideband, power in both IF channels: wanted minus "
        "image (dB) over the IF band; optionally Y-factor and Tn afterwards."
    )
    plots = (
        PlotSpec(
            "tone", "Test tone P-IF", "tone", "frequency", "power",
            x_label="IF, GHz", y_label="Power, dBm", x_scale=GHZ, group_by=("tone", "channel"),
        ),
        PlotSpec(
            "ratio", "SRR-IF", "ratio", "frequency", "power_difference",
            x_label="IF, GHz", y_label="P wanted - P image, dB", x_scale=GHZ, group_by=("tone",),
        ),
    ) + NOISE_PLOTS  # fmt: skip

    sis1_voltage = voltage_parameter("SIS1 bias", 2.6e-3)
    sis2_voltage = voltage_parameter("SIS2 bias", 2.4e-3)
    frequency = if_sweep()
    tones = ChoiceParameter("Test tone sidebands", SIDE_BAND_CHOICES, default="both")
    chunk_size = IntParameter(
        "Points per IF switch", default=10, minimum=1,
        help="IF points measured in one channel before switching to the other",
    )  # fmt: skip
    point_delay = FloatParameter("Point delay", default=0.05, minimum=0, unit="s")
    measure_y_factor = BoolParameter("Y-factor afterwards", default=True)

    def slots(self):
        slots = {
            **self.base_slots(),
            **self.lo_slots(),
            "test_tone": SOURCE,
            "if_selector": Switchable,
            **self.detector_slots(),
        }
        if self.measure_y_factor:
            slots.update(self.hot_cold_slots())
        return slots

    def check(self):
        return self.hot_cold_problems() if self.measure_y_factor else []

    def estimate_steps(self) -> int:
        tones = len(side_bands(self.tones)) * len(SIDE_BANDS) * self.frequency.points
        noise = (
            len(SIDE_BANDS) * 2 * self.frequency.points if self.measure_y_factor else 0
        )
        return tones + noise

    def run(self, ctx) -> None:
        self.start(ctx)
        self.prepare_lo(ctx)
        self.bias(ctx, self.sis1_voltage, self.sis2_voltage)
        ctx.record("bias", **self.read_bias(ctx))
        self.prepare_detector(ctx)
        if self.measure_y_factor:
            ctx["load"].to_hot()
        self.test_tone_on(ctx)
        tone = ctx["test_tone"]
        frequencies = self.frequency.values()
        chunks = [
            frequencies[i : i + self.chunk_size]
            for i in range(0, len(frequencies), self.chunk_size)
        ]
        for tone_side in side_bands(self.tones):
            for chunk in chunks:
                powers = {}
                for channel in SIDE_BANDS:
                    self.select_channel(ctx, channel, self.switch_delay)
                    for index, frequency in enumerate(chunk):
                        ctx.check_cancel()
                        tone.set_frequency(
                            test_tone_frequency(self.lo_frequency, frequency, tone_side)
                        )
                        power = self.read_tone(
                            ctx, frequency, index == 0, self.point_delay
                        )
                        powers[channel, frequency] = power
                        ctx.record(
                            "tone",
                            tone=tone_side,
                            channel=channel,
                            frequency=frequency,
                            power=power,
                        )
                        ctx.progress()
                for frequency in chunk:
                    ctx.record(
                        "ratio",
                        tone=tone_side,
                        frequency=frequency,
                        power_difference=power_difference(
                            powers["upper", frequency],
                            powers["lower", frequency],
                            tone_side,
                        ),
                    )
        tone.set_output(False)
        if self.measure_y_factor:
            self.measure_hot_cold(ctx, frequencies, SIDE_BANDS, self.switch_delay)


@register_procedure
class TwoSbNoise(LoMixin, HotColdMixin, TwoSbProcedure):
    name = "two_sb.tn"
    title = "2SB noise temperature"
    description = "Hot/cold Y-factor and Tn of the upper and lower IF channels."
    plots = NOISE_PLOTS

    lo_frequency = FloatParameter(
        "LO frequency",
        default=263 * GHZ,
        minimum=0,
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
    )
    sis1_voltage = voltage_parameter("SIS1 bias", 2.5e-3)
    sis2_voltage = voltage_parameter("SIS2 bias", 2.5e-3)
    frequency = if_sweep()
    channels = ChoiceParameter("IF channels", SIDE_BAND_CHOICES, default="both")
    tone_off = BoolParameter(
        "Switch the test tone off", default=False, help="Uses the 'test_tone' device"
    )

    def slots(self):
        slots = {**self.base_slots(), **self.lo_slots(), **self.hot_cold_slots()}
        if self.tone_off:
            slots["test_tone"] = SOURCE
        return slots

    def check(self):
        return self.hot_cold_problems()

    def estimate_steps(self) -> int:
        return len(side_bands(self.channels)) * 2 * self.frequency.points

    def run(self, ctx) -> None:
        self.start(ctx)
        if self.tone_off:
            ctx["test_tone"].set_output(False)
        self.prepare_lo(ctx)
        self.bias(ctx, self.sis1_voltage, self.sis2_voltage)
        ctx.record("bias", **self.read_bias(ctx))
        self.measure_hot_cold(
            ctx, self.frequency.values(), side_bands(self.channels), self.switch_delay
        )
