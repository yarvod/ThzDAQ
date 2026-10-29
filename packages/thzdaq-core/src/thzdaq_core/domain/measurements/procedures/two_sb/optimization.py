from thzdaq_api.leases import EXCLUSIVE, READ
from thzdaq_api.procedures import TWO_SB_OPTIMIZATION
from thzdaq_instruments.units import GHZ, MV

from thzdaq_analysis.noise import noise_temperature
from thzdaq_analysis.two_sb import (
    SIDE_BANDS,
    sideband_rejection,
    test_tone_frequency,
)
from thzdaq_api.measurement_file import KNOWN_COLUMNS
from thzdaq_core.domain.parameters import FloatParameter
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.domain.measurements.procedures.common import IFFrequency, set_bias
from thzdaq_core.domain.measurements.procedures.two_sb.common import (
    SOURCE,
    HotColdMixin,
    IfSwitchProcedure,
    LoMixin,
    SisBiasSweep,
)


def _map(column: str) -> PlotInfo:
    """A map over the bias grid of a column, titled as the column."""
    known = KNOWN_COLUMNS[column]
    return PlotInfo(
        column, known.title, "map", "sis1_voltage_set", "sis2_voltage_set",
        x_label="SIS1, mV", y_label="SIS2, mV", x_scale=MV, y_scale=MV,
        kind="map", z=column, z_label=known.unit,
    )  # fmt: skip


class TwoSbOptimization(LoMixin, HotColdMixin, IfSwitchProcedure):
    name = TWO_SB_OPTIMIZATION
    slot_modes = {"sis1": EXCLUSIVE, "sis2": EXCLUSIVE, "detector": READ}
    title = "2SB SRR/Tn bias optimization"
    description = (
        "At one IF over a SIS1 x SIS2 bias grid: test tone in both sidebands "
        "and hot/cold in both channels give SRR and Tn maps."
    )
    plots = (
        _map("tn_upper"),
        _map("tn_lower"),
        _map("srr_upper"),
        _map("srr_lower"),
    )

    if_frequency = IFFrequency(5 * GHZ)
    sis1_voltage = SisBiasSweep(1, (2.1e-3, 2.6e-3, 6))
    sis2_voltage = SisBiasSweep(2, (2.1e-3, 2.6e-3, 6))
    tone_delay = FloatParameter("Test tone delay", default=0.5, minimum=0, unit="s")

    def slots(self):
        return {
            **self.base_slots(),
            **self.lo_slots(),
            **self.hot_cold_slots(),
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
