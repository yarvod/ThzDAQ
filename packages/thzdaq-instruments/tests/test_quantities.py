import pytest
from thzdaq_instruments.quantities import Quantity, quantities_of, read_values
from thzdaq_instruments.sim import (
    SimPowerMeter,
    SimPowerSupply,
    SimSignalGenerator,
    SimSisBlock,
    SimYigFilter,
)


def keys(target):
    return [q.key for q in quantities_of(target)]


class TestQuantities:
    def test_from_capabilities(self):
        assert keys(SimPowerSupply().channel(1)) == [
            "output", "voltage_set", "current_set", "voltage", "current",
        ]  # fmt: skip
        assert keys(SimSignalGenerator()) == [
            "output", "frequency", "power_level", "frequency_multiplier",
            "oem_state", "oem_start", "oem_stop", "oem_multiplier",
        ]  # fmt: skip
        persistent = [
            q.key for q in quantities_of(SimSignalGenerator()) if q.persistent
        ]
        assert persistent[0] == "frequency_multiplier" and "frequency" not in persistent
        assert keys(SimPowerMeter())[:2] == ["power", "reading"]  # + NRX settings

    def test_driver_quantities(self):
        block = SimSisBlock()
        assert keys(block.channel("DEV4"))[-1] == "short"
        assert keys(block.ctrl("DEV3")) == ["current_set", "short"]

    def test_read_and_write(self):
        channel = SimPowerSupply().channel(2)
        by_key = {q.key: q for q in quantities_of(channel)}
        by_key["voltage_set"].write(channel, 1.5)
        by_key["output"].write(channel, 1)
        values = read_values(channel)
        assert values["voltage_set"] == 1.5 and values["output"] is True
        assert by_key["voltage"].label == "Voltage, V"
        assert not by_key["voltage"].settable and by_key["voltage"].readable

    def test_shared_source_is_called_once(self):
        calls = []
        channel = SimSisBlock().channel("DEV4")
        original = channel.measure

        def counted():
            calls.append(1)
            return original()

        channel.measure = counted
        values = read_values(channel)
        assert {"voltage", "current"} <= set(values) and len(calls) == 1

    def test_write_only_and_read_only(self):
        yig = SimYigFilter().channel("yig_1")
        frequency = quantities_of(yig)[0]
        assert frequency.settable and not frequency.readable
        with pytest.raises(AttributeError):
            frequency.read(yig)
        with pytest.raises(AttributeError):
            Quantity("x", "X", get=lambda t: 1).write(yig, 2)

    def test_subdevices_hide_reinterpreted_channels(self):
        assert SimSisBlock.fixed_channels() == ()
        assert set(SimSisBlock.subdevices) == {"sis_bias", "sis_coil"}
        assert SimPowerSupply.fixed_channels() == (1, 2, 3)
        block = SimSisBlock()
        assert block.part("ctrl", "DEV1") is block.ctrl("DEV1")


def test_generator_multiplier_like_the_instrument():
    generator = SimSignalGenerator(max_frequency=50e9, frequency_multiplier=18)
    generator.set_frequency(223e9)  # 12.4 GHz out of the generator
    assert generator.get_frequency() == 223e9
    generator.set_frequency_multiplier(1)
    with pytest.raises(Exception):
        generator.set_frequency(223e9)
