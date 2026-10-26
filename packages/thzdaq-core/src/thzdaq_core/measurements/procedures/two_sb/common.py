"""Shared pieces of the sideband separating (2SB) mixer procedures.

Device slots:
    sis1, sis2   bias of the two SIS mixers (VoltageSource + VoltageCurrentMeter)
    lo           LO generator (FrequencySource + Switchable); a multiplier after it is
                 set on the generator itself, so frequencies are at the mixer
    test_tone    RF test tone at the mixer frequency (FrequencySource + Switchable)
    if_selector  a supply channel switching the IF of the upper or lower sideband to
                 the detector (Switchable); which output state is "upper" is a parameter
    detector     PowerDetector after the IF filter
    if_filter    TunableFilter (YIG) in front of the detector
    load         LoadSwitch (chopper) for hot/cold
    yig_power    optional Switchable powering the YIG filter
    spectrum     SpectrumAnalyzer, alternative detector for the test tone
"""

from typing import Dict

from thzdaq_instruments.capabilities import (
    FrequencySource,
    LoadSwitch,
    PowerDetector,
    SpectrumAnalyzer,
    Switchable,
    TunableFilter,
)
from thzdaq_instruments.units import GHZ, KHZ, MV

from thzdaq_core.analysis.noise import noise_temperature
from thzdaq_core.analysis.two_sb import SIDE_BANDS
from thzdaq_core.measurements.parameters import (
    BoolParameter,
    ChoiceParameter,
    FloatParameter,
    IntParameter,
    SweepParameter,
)
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.common import (
    BIAS,
    restore_bias_on_exit,
    set_bias,
)

SOURCE = (FrequencySource, Switchable)
SIDE_BAND_CHOICES = ("both", "upper", "lower")


def voltage_parameter(label: str, default: float) -> FloatParameter:
    return FloatParameter(
        label, default=default, minimum=-30e-3, maximum=30e-3,
        unit="V", display_unit="mV", display_scale=MV,
    )  # fmt: skip


def if_sweep(default=(4 * GHZ, 12 * GHZ, 201)) -> SweepParameter:
    return SweepParameter(
        "IF", default=default, unit="Hz", display_unit="GHz", display_scale=GHZ
    )


class TwoSbProcedure(Procedure):
    """Bias both mixers, set the LO, measure IF channels; restore on exit."""

    precise_bias = BoolParameter(
        "Precise bias", default=True,
        help="Correct the bias by readback (slow: ~1 s per iteration)",
    )  # fmt: skip
    control_yig_power = BoolParameter(
        "Control YIG power",
        default=False,
        help="Switch on the 'yig_power' device first",
    )

    def base_slots(self) -> Dict[str, object]:
        slots = {"sis1": BIAS, "sis2": BIAS}
        if self.control_yig_power:
            slots["yig_power"] = Switchable
        return slots

    # Helpers for run()
    def start(self, ctx) -> None:
        """Call first in run(): remember the bias to restore, power the YIG."""
        restore_bias_on_exit(ctx, ctx["sis1"])
        restore_bias_on_exit(ctx, ctx["sis2"])
        if self.control_yig_power:
            ctx["yig_power"].set_output(True)

    def bias(self, ctx, voltage1: float, voltage2: float) -> None:
        set_bias(ctx["sis1"], voltage1, self.precise_bias)
        set_bias(ctx["sis2"], voltage2, self.precise_bias)

    def read_bias(self, ctx) -> Dict[str, float]:
        one, two = ctx["sis1"].measure(), ctx["sis2"].measure()
        return {
            "sis1_voltage": one.voltage,
            "sis1_current": one.current,
            "sis2_voltage": two.voltage,
            "sis2_current": two.current,
        }

    @staticmethod
    def test_tone_on(ctx) -> None:
        tone = ctx["test_tone"]
        ctx.on_exit(lambda: tone.set_output(False))
        tone.set_output(True)


class IfSwitchProcedure(TwoSbProcedure):
    """2SB measurement reading both IF channels through the IF switch."""

    switch_delay = FloatParameter("IF switch delay", default=1.0, minimum=0, unit="s")
    upper_when_on = BoolParameter(
        "IF switch on: upper",
        default=True,
        help="On: the IF switch channel routes the upper sideband when its output "
        "is on; off: when it is off",
    )

    def select_channel(self, ctx, side_band: str, delay: float) -> None:
        if side_band not in ("upper", "lower"):
            raise ValueError(f"Unknown sideband {side_band!r}")
        ctx["if_selector"].set_output((side_band == "upper") == self.upper_when_on)
        ctx.sleep(delay)


class LoMixin:
    """Optional LO setting: frequency at the mixer, output on."""

    lo_frequency = FloatParameter(
        "LO frequency",
        default=223 * GHZ,
        minimum=0,
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
    )
    set_lo = BoolParameter("Set LO", default=True)

    def lo_slots(self):
        return {"lo": SOURCE} if self.set_lo else {}

    def prepare_lo(self, ctx) -> None:
        if self.set_lo:
            lo = ctx["lo"]
            lo.set_output(True)
            lo.set_frequency(self.lo_frequency)


class HotColdMixin:
    """Y-factor and Tn of each IF channel through the YIG and the power meter."""

    t_hot = FloatParameter("Hot load", default=300.0, minimum=0, unit="K")
    t_cold = FloatParameter("Cold load", default=77.0, minimum=0, unit="K")
    load_delay = FloatParameter("Load switch delay", default=0.5, minimum=0, unit="s")
    point_delay = FloatParameter("Point delay", default=0.01, minimum=0, unit="s")

    @staticmethod
    def hot_cold_slots():
        return {
            "if_selector": Switchable,
            "detector": PowerDetector,
            "if_filter": TunableFilter,
            "load": LoadSwitch,
        }

    def hot_cold_problems(self):
        return (
            ["hot load must be warmer than the cold one"]
            if self.t_hot <= self.t_cold
            else []
        )

    def measure_hot_cold(self, ctx, frequencies, side_bands, switch_delay) -> None:
        load, detector, if_filter = ctx["load"], ctx["detector"], ctx["if_filter"]
        ctx.on_exit(load.to_cold)
        for side_band in side_bands:
            ctx.check_cancel()
            self.select_channel(ctx, side_band, switch_delay)
            powers = {}
            for state in ("cold", "hot"):
                getattr(load, f"to_{state}")()
                ctx.sleep(self.load_delay)
                for frequency in frequencies:
                    ctx.check_cancel()
                    actual = if_filter.tune(frequency)
                    ctx.sleep(self.point_delay)
                    power = detector.read_power()
                    powers[state, frequency] = power
                    ctx.record(
                        "power",
                        channel=side_band,
                        load=state,
                        frequency=actual,
                        power=power,
                    )
                    ctx.progress()
            for frequency in frequencies:
                hot, cold = powers["hot", frequency], powers["cold", frequency]
                ctx.record(
                    "noise",
                    channel=side_band,
                    frequency=frequency,
                    y_factor=hot - cold,
                    noise_temperature=noise_temperature(
                        hot, cold, self.t_hot, self.t_cold
                    ),
                )


class SpectrumMixin:
    """Test tone peak on the spectrum analyzer instead of YIG + power meter."""

    detector = ChoiceParameter(
        "Detector", ("power_meter", "spectrum"), default="power_meter"
    )
    resolution_bandwidth = FloatParameter(
        "RBW",
        default=200 * KHZ,
        minimum=1,
        unit="Hz",
        display_unit="kHz",
        display_scale=KHZ,
    )
    video_bandwidth = FloatParameter(
        "VBW",
        default=20 * KHZ,
        minimum=1,
        unit="Hz",
        display_unit="kHz",
        display_scale=KHZ,
    )
    span = FloatParameter(
        "Span",
        default=100 * KHZ,
        minimum=1,
        unit="Hz",
        display_unit="kHz",
        display_scale=KHZ,
    )
    averages = IntParameter("Peak averages", default=5, minimum=1, maximum=100)
    retune_delay = FloatParameter(
        "Retune delay", default=0.1, minimum=0, unit="s",
        help="Wait after moving the analyzer; doubled x20 on the first point of a chunk",
    )  # fmt: skip

    def detector_slots(self):
        if self.detector == "spectrum":
            return {"spectrum": SpectrumAnalyzer}
        return {"detector": PowerDetector, "if_filter": TunableFilter}

    def prepare_detector(self, ctx) -> None:
        if self.detector != "spectrum":
            return
        spectrum = ctx["spectrum"]
        if hasattr(spectrum, "set_continuous_sweep"):
            spectrum.set_continuous_sweep(False)
        spectrum.set_video_bandwidth(self.video_bandwidth)
        spectrum.set_resolution_bandwidth(self.resolution_bandwidth)
        spectrum.set_span(self.span)

    def read_tone(
        self, ctx, if_frequency: float, first: bool, point_delay: float
    ) -> float:
        if self.detector != "spectrum":
            ctx["if_filter"].tune(if_frequency)
            ctx.sleep(point_delay)
            return ctx["detector"].read_power()
        spectrum = ctx["spectrum"]
        spectrum.set_center_frequency(if_frequency)
        ctx.sleep(self.retune_delay * (20 if first else 1))
        trigger = getattr(spectrum, "trigger", None)
        if trigger is not None:
            trigger()
        levels = [spectrum.read_peak()[1] for _ in range(self.averages)]
        return sum(levels) / len(levels)


def side_bands(choice: str):
    return SIDE_BANDS if choice == "both" else (choice,)
