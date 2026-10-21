from thzdaq_instruments.units import GHZ, MV

from thzdaq_core.analysis.noise import noise_temperature
from thzdaq_core.analysis.two_sb import (
    SIDE_BANDS,
    sideband_rejection,
    test_tone_frequency,
)
from thzdaq_core.measurements.parameters import FloatParameter, SweepParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedures.common import set_bias
from thzdaq_core.measurements.procedures.two_sb.common import (
    SOURCE,
    HotColdMixin,
    LoMixin,
    TwoSbProcedure,
)
from thzdaq_core.measurements.registry import register_procedure


def _map(key: str, title: str, z: str, z_label: str) -> PlotSpec:
    return PlotSpec(
        key, title, "map", "sis1_voltage_set", "sis2_voltage_set",
        x_label="SIS1, mV", y_label="SIS2, mV", x_scale=MV, y_scale=MV,
        kind="map", z=z, z_label=z_label,
    )  # fmt: skip


@register_procedure
class TwoSbOptimization(LoMixin, HotColdMixin, TwoSbProcedure):
    name = "two_sb.optimization"
    title = "2SB SRR/Tn bias optimization"
    description = (
        "At one IF over a SIS1 x SIS2 bias grid: test tone in both sidebands "
        "and hot/cold in both channels give SRR and Tn maps."
    )
    plots = (
        _map("tn_upper", "Tn upper", "tn_upper", "K"),
        _map("tn_lower", "Tn lower", "tn_lower", "K"),
        _map("srr_upper", "SRR upper", "srr_upper", "dB"),
        _map("srr_lower", "SRR lower", "srr_lower", "dB"),
    )

    if_frequency = FloatParameter(
        "IF",
        default=5 * GHZ,
        minimum=0,
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
    )
    sis1_voltage = SweepParameter(
        "SIS1 bias",
        default=(2.1e-3, 2.6e-3, 6),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    sis2_voltage = SweepParameter(
        "SIS2 bias",
        default=(2.1e-3, 2.6e-3, 6),
        unit="V",
        display_unit="mV",
        display_scale=MV,
    )
    tone_delay = FloatParameter("Test tone delay", default=0.5, minimum=0, unit="s")

    def roles(self):
        return {
            **self.base_roles(),
            **self.lo_roles(),
            **self.hot_cold_roles(),
            "test_tone": SOURCE,
        }

    def check(self):
        return self.hot_cold_problems()

    def estimate_steps(self) -> int:
        return self.sis1_voltage.points * self.sis2_voltage.points

    def read_settled(self, ctx) -> float:
        detector = ctx["detector"]
        # The meter keeps averaging over the IF switch transient: drop two readings
        detector.read_power()
        detector.read_power()
        return detector.read_power()

    def run(self, ctx) -> None:
        self.start(ctx)
        self.prepare_lo(ctx)
        tone, load = ctx["test_tone"], ctx["load"]
        ctx.on_exit(load.to_cold)
        ctx.on_exit(lambda: tone.set_output(False))
        ctx["if_filter"].tune(self.if_frequency)
        load.to_hot()
        for v1 in self.sis1_voltage.values():
            ctx.check_cancel()
            set_bias(ctx["sis1"], v1, self.precise_bias)
            for v2 in self.sis2_voltage.values():
                ctx.check_cancel()
                set_bias(ctx["sis2"], v2, self.precise_bias)
                bias = self.read_bias(ctx)

                tone.set_output(True)
                ctx.sleep(self.tone_delay)
                tone_powers = {}
                for tone_side in SIDE_BANDS:
                    tone.set_frequency(
                        test_tone_frequency(
                            self.lo_frequency, self.if_frequency, tone_side
                        )
                    )
                    ctx.sleep(self.tone_delay)
                    for channel in SIDE_BANDS:
                        self.select_channel(ctx, channel, self.switch_delay)
                        tone_powers[tone_side, channel] = self.read_settled(ctx)
                tone.set_output(False)

                loads = {}
                for channel in SIDE_BANDS:
                    self.select_channel(ctx, channel, self.switch_delay)
                    for state in ("cold", "hot"):
                        getattr(load, f"to_{state}")()
                        ctx.sleep(self.load_delay)
                        loads[channel, state] = ctx["detector"].read_power()

                srr_upper, srr_lower = sideband_rejection(
                    loads["upper", "hot"],
                    loads["upper", "cold"],
                    loads["lower", "hot"],
                    loads["lower", "cold"],
                    usb_power_upper=tone_powers["upper", "upper"],
                    usb_power_lower=tone_powers["upper", "lower"],
                    lsb_power_upper=tone_powers["lower", "upper"],
                    lsb_power_lower=tone_powers["lower", "lower"],
                )
                ctx.record(
                    "map",
                    sis1_voltage_set=v1,
                    sis2_voltage_set=v2,
                    **bias,
                    tn_upper=noise_temperature(
                        loads["upper", "hot"],
                        loads["upper", "cold"],
                        self.t_hot,
                        self.t_cold,
                    ),
                    tn_lower=noise_temperature(
                        loads["lower", "hot"],
                        loads["lower", "cold"],
                        self.t_hot,
                        self.t_cold,
                    ),
                    srr_upper=srr_upper,
                    srr_lower=srr_lower,
                    tone_powers={f"{t}_{c}": p for (t, c), p in tone_powers.items()},
                    load_powers={f"{c}_{s}": p for (c, s), p in loads.items()},
                )
                ctx.progress()
