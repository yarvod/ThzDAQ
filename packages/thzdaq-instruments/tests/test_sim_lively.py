import pytest
from thzdaq_instruments.sim import (
    SimCompressor,
    SimPowerMeter,
    SimPowerSupply,
    SimSisBlock,
    SimTemperatureController,
    SimVacuumGauge,
)

READINGS = {
    "power meter": (SimPowerMeter, lambda i: i.read_power()),
    "temperature": (SimTemperatureController, lambda i: i.channel("A").read_temperature()),
    "vacuum": (SimVacuumGauge, lambda i: i.read_pressure()),
    "compressor": (SimCompressor, lambda i: tuple(i.read_temperatures() + i.read_pressures())),
    "sis bias": (SimSisBlock, lambda i: i.channel("DEV4").measure()),
    "supply": (SimPowerSupply, lambda i: i.channel(1).measure()),
}  # fmt: skip


def prepare(instrument):
    if isinstance(instrument, SimSisBlock):
        instrument.channel("DEV4").set_voltage(3e-3)
    if isinstance(instrument, SimPowerSupply):
        instrument.channel(1).set_voltage(5.0)
        instrument.channel(1).set_output(True)
    return instrument


@pytest.mark.parametrize("name", READINGS)
def test_exact_by_default_alive_after_liven(name):
    cls, read = READINGS[name]
    instrument = prepare(cls())
    assert len({read(instrument) for _ in range(5)}) == 1
    instrument.liven()
    values = {read(instrument) for _ in range(5)}
    assert len(values) == 5


def test_lively_values_stay_close():
    meter = SimPowerMeter(power=-30.0)
    meter.liven()
    assert all(abs(meter.read_power() + 30.0) < 1.0 for _ in range(100))
