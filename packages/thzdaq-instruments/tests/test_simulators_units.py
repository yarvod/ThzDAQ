import math

import pytest
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.sim import (
    SimChopper,
    SimPowerMeter,
    SimPowerSupply,
    SimSignalGenerator,
    SimSisBlock,
    SimYigFilter,
)
from thzdaq_instruments.units import (
    GHZ,
    db_to_ratio,
    dbm_to_watt,
    ratio_to_db,
    watt_to_dbm,
)


class TestUnits:
    def test_dbm_roundtrip(self):
        assert dbm_to_watt(0) == pytest.approx(1e-3)
        assert watt_to_dbm(dbm_to_watt(-32.5)) == pytest.approx(-32.5)

    def test_db_roundtrip(self):
        assert db_to_ratio(3) == pytest.approx(1.995, rel=1e-3)
        assert ratio_to_db(db_to_ratio(2)) == pytest.approx(2)

    @pytest.mark.parametrize("func", [watt_to_dbm, ratio_to_db])
    def test_non_positive_rejected(self, func):
        with pytest.raises(ValueError):
            func(0)

    def test_reading_power(self):
        assert ChannelReading(2.0, 0.5).power == 1.0


class TestSimulators:
    def test_supply_output_off_reads_zero(self):
        channel = SimPowerSupply().channel(1)
        channel.set_voltage(5)
        assert channel.measure() == ChannelReading(0.0, 0.0)

    def test_supply_constant_voltage_and_current_limit(self):
        channel = SimPowerSupply(load_resistances={1: 10.0}).channel(1)
        channel.set_output(True)
        channel.set_voltage(5)
        channel.set_current(1)
        assert channel.measure() == ChannelReading(5.0, 0.5)
        channel.set_current(0.2)
        assert channel.measure() == ChannelReading(2.0, 0.2)

    def test_supply_rejects_out_of_range(self):
        channel = SimPowerSupply(max_voltage=10).channel(1)
        with pytest.raises(InstrumentResponseError):
            channel.set_voltage(11)

    def test_generator_rejects_out_of_range(self):
        generator = SimSignalGenerator()
        with pytest.raises(InstrumentResponseError):
            generator.set_frequency(100 * GHZ)
        with pytest.raises(InstrumentResponseError):
            generator.set_power(30)

    def test_sis_iv_has_gap(self):
        block = SimSisBlock(normal_resistance=20, subgap_resistance=500)
        bias = block.channel("DEV4")
        bias.set_voltage(1e-3)
        below = bias.measure().current
        bias.set_voltage(5e-3)
        above = bias.measure().current
        assert below == pytest.approx(1e-3 / 500, rel=1e-3)
        assert above == pytest.approx(5e-3 / 500 + 5e-3 / 20, rel=1e-3)
        bias.set_voltage(-5e-3)
        assert bias.measure().current == pytest.approx(-above)

    def test_yig_quantizes_and_clamps(self):
        yig = SimYigFilter(start_frequency=3e9, step=2e6, max_code=100)
        assert yig.tune(3.0031e9) == pytest.approx(3.004e9)
        assert yig.tune(1e9) == pytest.approx(3e9)
        assert yig.tune(10e9) == pytest.approx(3.2e9)

    def test_power_meter_model_couples_with_chopper(self):
        chopper = SimChopper()
        meter = SimPowerMeter(
            model=lambda: -30.0 if chopper.position == "hot" else -32.0
        )
        assert meter.read_power() == -32.0
        chopper.to_hot()
        assert meter.read_power() == -30.0
        chopper.to_hot()
        assert chopper.moves == 1

    def test_power_meter_noise_is_reproducible(self):
        first = SimPowerMeter(noise=0.1, seed=7)
        second = SimPowerMeter(noise=0.1, seed=7)
        values = [first.read_power() for _ in range(5)]
        assert values == [second.read_power() for _ in range(5)]
        assert not all(math.isclose(v, -30.0) for v in values)
