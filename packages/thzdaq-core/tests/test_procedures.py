import math

import pytest
from thzdaq_core.analysis.noise import match_hot_cold, noise_temperature
from thzdaq_core.analysis.shot_noise import dynamic_resistance, linear_fit
from thzdaq_core.analysis.two_sb import sideband_rejection
from thzdaq_core.data import COMPLETED, DeviceUse
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements import MeasurementRunner, get_procedure
from thzdaq_core.measurements.procedures import (
    GridCurrentAngle,
    IfBalance,
    PumpBalance,
    PVCurve,
    ShotNoise,
    SidebandRatio,
    SisReflection,
    TwoSbNoise,
    TwoSbOptimization,
    YFactorVoltage,
)
from thzdaq_instruments.sim import (
    SimChopper,
    SimNetworkAnalyzer,
    SimPowerMeter,
    SimPowerSupply,
    SimRotator,
    SimSignalGenerator,
    SimSisBlock,
    SimYigFilter,
)

LO = 223e9
FAST = {"switch_delay": 0, "precise_bias": False}
FAST_NOISE = {**FAST, "load_delay": 0, "point_delay": 0}


class Bench:
    """Coupled simulators of a 2SB receiver.

    Noise: hot -30 dBm, cold -32 dBm (+0.5 dB in the lower channel).
    Test tone: -20 dBm in the wanted channel, -40 dBm in the image (20 dB SRR).
    """

    def __init__(self):
        self.chopper = SimChopper()
        # IF switch: a supply channel, output on = upper sideband (the default)
        self.switch = SimPowerSupply().channel(2)
        # LO generator with its x18 multiplier set: frequencies at the mixer
        self.lo = SimSignalGenerator(max_frequency=50e9, frequency_multiplier=18)
        self.tone = SimSignalGenerator(max_frequency=400e9)
        self.lo.set_frequency(LO)
        block = SimSisBlock()
        self.ports = {
            "sis1": block.channel("DEV4"),
            "sis2": block.channel("DEV2"),
            "bias": block.channel("DEV4"),
            "lo": self.lo,
            "test_tone": self.tone,
            "if_selector": self.switch,
            "detector": SimPowerMeter(model=self.power),
            "if_filter": SimYigFilter().channel("yig_1"),
            "load": self.chopper,
            "yig_power": SimPowerSupply().channel(1),
            "spectrum": self,
            "vna": SimNetworkAnalyzer(),
            "grid": SimRotator(),
        }

    def power(self) -> float:
        channel = "upper" if self.switch.get_output() else "lower"
        if self.tone.get_output():
            tone_side = (
                "upper"
                if self.tone.get_frequency() > self.lo.get_frequency()
                else "lower"
            )
            return -20.0 if tone_side == channel else -40.0
        base = -30.0 if self.chopper.position == "hot" else -32.0
        return base + (0.5 if channel == "lower" else 0.0)

    # Spectrum analyzer port: the tone peak follows the same model
    def set_center_frequency(self, frequency):
        ...

    def set_span(self, span):
        ...

    def set_resolution_bandwidth(self, bandwidth):
        ...

    def set_video_bandwidth(self, bandwidth):
        ...

    def read_peak(self):
        return 0.0, self.power()

    def read_trace(self):
        ...

    # StationLike
    def require(self, devices, requirements):
        return {slot: self.ports[slot] for slot in requirements}

    def device_use(self, ref):
        return DeviceUse(ref)

    def snapshot(self, refs=None):
        return {"station": {"name": "sim 2sb bench"}}


def run(procedure, bench=None, **devices):
    bench = bench or Bench()
    dataset = MeasurementRunner(bench).run(procedure, devices=devices)
    assert dataset.status == COMPLETED, dataset.error
    return dataset, bench


class TestSisProcedures:
    def test_pv_curve_with_hot_cold_and_grid(self):
        procedure = PVCurve(
            voltage=(1e-3, 4e-3, 4),
            hot_cold=True,
            use_grid=True,
            angle=(0, 30, 2),
            settle_time=0,
            first_point_delay=0,
            load_delay=0,
            grid_speed=1e6,
        )
        dataset, bench = run(procedure)
        assert len(dataset.records("pv")) == 2 * 2 * 4
        y = dataset.records("y_factor")
        assert len(y) == 8 and y[0]["y_factor"] == pytest.approx(2.0)
        assert y[0]["noise_temperature"] == pytest.approx(noise_temperature(-30, -32))
        assert bench.ports["grid"].get_angle() == 0  # restored
        assert bench.chopper.position == "cold"
        assert set(procedure.slots()) == {"bias", "detector", "load", "grid"}

    def test_y_factor_voltage_needs_the_load(self):
        assert "load" in YFactorVoltage().slots()
        assert "load" not in PVCurve().slots()

    def test_reflection_records_traces(self):
        procedure = SisReflection(
            voltage=(0, 3e-3, 3),
            frequency=(2e9, 4e9, 5),
            s_parameters=("S11", "S21"),
            samples=2,
            averaging_time=0,
            first_point_delay=0,
        )
        dataset, bench = run(procedure)
        traces = dataset.records("trace")
        assert len(traces) == 3 * 2 * 2 and len(traces[0]["values"]) == 5
        assert {t["parameter"] for t in traces} == {"S11", "S21"}
        assert dataset.results["frequency"][-1] == 4e9
        assert bench.ports["vna"].averaging == 1
        assert dataset.records("summary")[0]["magnitude_db"] == pytest.approx(
            20 * math.log10(1 / 3), abs=1e-6
        )

    def test_grid_current_angle(self):
        dataset, bench = run(
            GridCurrentAngle(angle=(0, 90, 4), grid_speed=1e6, settle_time=0)
        )
        assert [r["angle"] for r in dataset.records("ia")] == [0, 30, 60, 90]
        assert bench.ports["grid"].get_angle() == 0

    def test_shot_noise_fits_resistance(self):
        procedure = ShotNoise(
            voltage1=15e-3,
            voltage2=20e-3,
            resistance_points=5,
            frequency=(4e9, 5e9, 3),
            settle_time=0,
            point_delay=0,
        )
        dataset, _ = run(procedure)
        # Above the gap the simulated SIS is 20 Ohm || 500 Ohm
        assert dataset.results["rd1"] == pytest.approx(1 / (1 / 20 + 1 / 500), rel=1e-3)
        assert len(dataset.records("noise")) == 3
        # Constant simulated IF power: no contrast between points
        assert math.isnan(dataset.records("noise")[0]["amplifier_temperature"])


class TestTwoSb:
    def test_if_balance(self):
        procedure = IfBalance(
            sis1_voltages=(5e-3, 6e-3), sis2_voltages=(5e-3,), frequency=(4e9, 5e9, 3),
            point_delay=0, **FAST,
        )  # fmt: skip
        dataset, _ = run(procedure)
        power = dataset.records("power")
        assert len(power) == 2 * 2 * 3
        assert {r["bias"] for r in power} == {"5.00/5.00 mV", "6.00/5.00 mV"}
        lower = [r["power"] for r in power if r["channel"] == "lower"]
        assert lower[0] == pytest.approx(-31.5)

    def test_pump_balance_rf(self):
        procedure = PumpBalance(
            source="test_tone", frequency=(220e9, 221e9, 2),
            sis1_voltage=(2.4e-3, 2.6e-3, 3), sis2_voltage=(2.4e-3, 2.6e-3, 3),
            bias_delay=0, measure_power=True,
        )  # fmt: skip
        dataset, bench = run(procedure)
        assert len(dataset.records("pump")) == 6
        assert bench.lo.get_output() is False and bench.lo.get_power() == -80
        assert bench.tone.get_output() is False  # switched off on exit
        assert set(procedure.slots()) == {"sis1", "sis2", "test_tone", "lo", "detector"}

    def test_pump_balance_checks_paired_sweeps(self):
        with pytest.raises(ProcedureError, match="same number"):
            PumpBalance(sis2_voltage=(2e-3, 3e-3, 5)).validate()

    @pytest.mark.parametrize("detector", ["power_meter", "spectrum"])
    def test_srr_with_y_factor(self, detector):
        procedure = SidebandRatio(
            lo_frequency=LO, frequency=(4e9, 6e9, 5), chunk_size=2, detector=detector,
            retune_delay=0, averages=2, control_yig_power=True, **FAST_NOISE,
        )  # fmt: skip
        dataset, bench = run(procedure)
        ratio = dataset.records("ratio")
        assert len(ratio) == 2 * 5
        assert all(r["power_difference"] == pytest.approx(20.0) for r in ratio)
        noise = dataset.records("noise")
        assert {r["channel"] for r in noise} == {"upper", "lower"}
        assert noise[0]["y_factor"] == pytest.approx(2.0)
        assert bench.tone.get_output() is False and bench.chopper.position == "cold"
        assert bench.ports["yig_power"].get_output() is True
        assert bench.ports["sis1"].get_voltage() == 0.0  # bias restored
        roles = procedure.slots()
        assert ("spectrum" in roles) == (detector == "spectrum")

    def test_srr_without_y_factor_needs_no_load(self):
        procedure = SidebandRatio(measure_y_factor=False, set_lo=False)
        assert {"load", "lo"}.isdisjoint(procedure.slots())

    def test_tn_both_channels(self):
        procedure = TwoSbNoise(frequency=(4e9, 5e9, 2), tone_off=True, **FAST_NOISE)
        dataset, bench = run(procedure)
        noise = dataset.records("noise")
        lower = [r for r in noise if r["channel"] == "lower"]
        assert len(noise) == 4
        assert lower[0]["noise_temperature"] == pytest.approx(
            noise_temperature(-29.5, -31.5)
        )
        assert bench.lo.get_frequency() == pytest.approx(263e9)

    def test_optimization_maps(self):
        procedure = TwoSbOptimization(
            lo_frequency=LO, if_frequency=5e9,
            sis1_voltage=(2.1e-3, 2.2e-3, 2), sis2_voltage=(2.1e-3, 2.3e-3, 3),
            tone_delay=0, **FAST_NOISE,
        )  # fmt: skip
        dataset, _ = run(procedure)
        maps = dataset.records("map")
        assert len(maps) == 6
        expected = sideband_rejection(-30, -32, -29.5, -31.5, -20, -40, -40, -20)
        assert maps[0]["srr_upper"] == pytest.approx(expected[0])
        assert maps[0]["srr_lower"] == pytest.approx(expected[1])
        assert maps[0]["tn_upper"] == pytest.approx(noise_temperature(-30, -32))
        spec = TwoSbOptimization.plots[0]
        assert spec.point(maps[0]) == pytest.approx((2.1, 2.1, maps[0]["tn_upper"]))


class TestAnalysis:
    def test_match_hot_cold_pairs_nearest_voltage(self):
        hot = [(1.0, -30), (2.0, -29), (3.0, -28)]
        cold = [(1.1, -32), (1.9, -31), (3.05, -30)]
        assert match_hot_cold(hot, cold, window=2) == [
            (1.0, -30, -32),
            (2.0, -29, -31),
            (3.0, -28, -30),
        ]

    def test_linear_fit_and_resistance(self):
        assert linear_fit([0, 1, 2], [1, 3, 5]) == pytest.approx((2, 1))
        assert dynamic_resistance([0, 1e-3], [0, 50e-6]) == pytest.approx(20)
        with pytest.raises(ValueError):
            linear_fit([1, 1], [1, 2])

    def test_srr_of_ideal_mixer_matches_tone_ratio(self):
        # Equal channel gains: SRR equals the tone ratio
        upper, lower = sideband_rejection(-30, -32, -30, -32, -20, -40, -40, -20)
        assert upper == pytest.approx(20) and lower == pytest.approx(20)


def test_all_registered_procedures_have_valid_defaults():
    for name in [
        "sis.iv_curve", "sis.pv_curve", "sis.y_factor_voltage", "sis.reflection",
        "sis.shot_noise", "grid.current_angle", "if.hot_cold", "two_sb.if_balance",
        "two_sb.pump_balance", "two_sb.srr", "two_sb.tn", "two_sb.optimization",
    ]:  # fmt: skip
        procedure = get_procedure(name)()
        procedure.validate()
        assert procedure.slots()
        assert procedure.estimate_steps() > 0
        for spec in procedure.plots:
            assert spec.table and spec.x and spec.y


def test_if_switch_polarity_is_a_parameter():
    """With upper_when_on=False the same channel off routes the upper sideband."""
    bench = Bench()
    procedure = TwoSbNoise(
        frequency=(4e9, 5e9, 2), channels="upper", upper_when_on=False, set_lo=False,
        **FAST_NOISE,
    )  # fmt: skip
    seen = []
    original = bench.switch.set_output
    bench.switch.set_output = lambda value: (seen.append(value), original(value))
    run(procedure, bench)
    assert seen and seen[0] is False


def test_if_switch_parameters_only_where_the_switch_is_used():
    from thzdaq_core.measurements.registry import get_procedure

    for name in ("two_sb.if_balance", "two_sb.srr", "two_sb.tn", "two_sb.optimization"):
        parameters = get_procedure(name).parameters()
        assert "upper_when_on" in parameters and "switch_delay" in parameters
    pump = get_procedure("two_sb.pump_balance")
    assert "upper_when_on" not in pump.parameters()
    assert "if_selector" not in pump().slots()
