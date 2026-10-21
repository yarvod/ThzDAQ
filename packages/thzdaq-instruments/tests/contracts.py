"""Behaviour every implementation of a capability must have (LSP).

Factories create a fresh instrument or channel. Real drivers join these lists
with a FakeLink-backed transport, so drivers and simulators pass the same checks.
"""

import math

from thzdaq_instruments.capabilities import (
    CurrentSource,
    FrequencySource,
    Identifiable,
    LoadSwitch,
    PowerDetector,
    PowerLevel,
    Switchable,
    TunableFilter,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.sim import (
    SimChopper,
    SimPowerMeter,
    SimPowerSupply,
    SimSignalGenerator,
    SimSisBlock,
    SimYigFilter,
)


def check_identifiable(device):
    identity = device.identify()
    assert isinstance(identity, str) and identity


def check_switchable(device):
    device.set_output(True)
    assert device.get_output() is True
    device.set_output(False)
    assert device.get_output() is False


def check_voltage_source(device):
    device.set_voltage(1.5e-3)
    assert math.isclose(device.get_voltage(), 1.5e-3, rel_tol=1e-6)


def check_current_source(device):
    device.set_current(0.5)
    assert math.isclose(device.get_current(), 0.5, rel_tol=1e-6)


def check_voltage_current_meter(device):
    reading = device.measure()
    assert isinstance(reading, ChannelReading)
    assert isinstance(reading.voltage, float) and isinstance(reading.current, float)


def check_frequency_source(device):
    device.set_frequency(5e9)
    assert math.isclose(device.get_frequency(), 5e9, rel_tol=1e-9)


def check_power_level(device):
    device.set_power(-10.0)
    assert math.isclose(device.get_power(), -10.0, abs_tol=1e-9)


def check_power_detector(device):
    assert isinstance(device.read_power(), float)


def check_tunable_filter(device):
    actual = device.tune(6e9)
    assert isinstance(actual, float)
    assert abs(actual - 6e9) < 5e6


def check_load_switch(device):
    device.to_hot()
    device.to_cold()


CONTRACTS = {
    Identifiable: (
        check_identifiable,
        {
            "sim power supply": SimPowerSupply,
            "sim signal generator": SimSignalGenerator,
            "sim power meter": SimPowerMeter,
            "sim sis block": SimSisBlock,
            "sim yig filter": SimYigFilter,
            "sim chopper": SimChopper,
        },
    ),
    Switchable: (
        check_switchable,
        {
            "sim supply channel": lambda: SimPowerSupply().channel(1),
            "sim signal generator": SimSignalGenerator,
        },
    ),
    VoltageSource: (
        check_voltage_source,
        {
            "sim supply channel": lambda: SimPowerSupply().channel(2),
            "sim sis bias": lambda: SimSisBlock().channel("DEV4"),
        },
    ),
    CurrentSource: (
        check_current_source,
        {"sim supply channel": lambda: SimPowerSupply().channel(3)},
    ),
    VoltageCurrentMeter: (
        check_voltage_current_meter,
        {
            "sim supply channel": lambda: SimPowerSupply().channel(1),
            "sim sis bias": lambda: SimSisBlock().channel("DEV2"),
        },
    ),
    FrequencySource: (
        check_frequency_source,
        {"sim signal generator": SimSignalGenerator},
    ),
    PowerLevel: (check_power_level, {"sim signal generator": SimSignalGenerator}),
    PowerDetector: (check_power_detector, {"sim power meter": SimPowerMeter}),
    TunableFilter: (check_tunable_filter, {"sim yig filter": SimYigFilter}),
    LoadSwitch: (check_load_switch, {"sim chopper": SimChopper}),
}


def contract_cases():
    for capability, (check, factories) in CONTRACTS.items():
        for label, factory in factories.items():
            yield f"{capability.__name__}-{label}", capability, check, factory
