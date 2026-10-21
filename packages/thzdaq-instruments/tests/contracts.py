"""Behaviour every implementation of a capability must have (LSP).

Factories create a fresh instrument or channel. Real drivers join these lists
with a FakeLink-backed transport, so drivers and simulators pass the same checks.
"""

import math

from emulators import (
    AgilentEmulator,
    FakeJsonClient,
    HmpEmulator,
    KeithleyEmulator,
    MotorRegisters,
    NrxEmulator,
    RigolEmulator,
    SisEmulator,
)
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
from thzdaq_instruments.drivers import (
    AgilentE8247C,
    Keithley2200,
    ModbusChopper,
    NiYigFilter,
    RigolDP832A,
    RohdeSchwarzHMP2030,
    RohdeSchwarzNRX,
    ScontelSisBlock,
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


def driver(cls, emulator):
    transport, _ = emulator.transport()
    return cls(transport)


def rigol():
    return driver(RigolDP832A, RigolEmulator())


def hmp():
    return driver(RohdeSchwarzHMP2030, HmpEmulator())


def keithley():
    return driver(Keithley2200, KeithleyEmulator())


def agilent():
    return driver(AgilentE8247C, AgilentEmulator())


def nrx():
    return driver(RohdeSchwarzNRX, NrxEmulator())


def sis():
    return driver(ScontelSisBlock, SisEmulator())


def yig():
    return NiYigFilter(client=FakeJsonClient())


def chopper():
    return ModbusChopper(
        registers=MotorRegisters(), move_wait=0, align_wait=0, step_wait=0
    )


SUPPLY_CHANNELS = {
    "sim supply channel": lambda: SimPowerSupply().channel(1),
    "rigol channel": lambda: rigol().channel(2),
    "hmp channel": lambda: hmp().channel(3),
    "keithley channel": lambda: keithley().channel(1),
}


def check_identifiable(device):
    identity = device.identify()
    assert isinstance(identity, str) and identity


def check_switchable(device):
    device.set_output(True)
    assert device.get_output() is True
    device.set_output(False)
    assert device.get_output() is False


def check_voltage_source(device, voltage=1.5):
    device.set_voltage(voltage)
    assert math.isclose(device.get_voltage(), voltage, rel_tol=1e-6)


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
            "rigol": rigol,
            "hmp": hmp,
            "keithley": keithley,
            "agilent": agilent,
            "nrx": nrx,
            "sis": sis,
            "yig": yig,
            "chopper": chopper,
        },
    ),
    Switchable: (
        check_switchable,
        {
            **SUPPLY_CHANNELS,
            "sim signal generator": SimSignalGenerator,
            "agilent": agilent,
        },
    ),
    VoltageSource: (
        check_voltage_source,
        {
            **SUPPLY_CHANNELS,
            "sim sis bias": (
                lambda: SimSisBlock().channel("DEV4"),
                {"voltage": 1.5e-3},
            ),
            "sis bias": (lambda: sis().channel("DEV4"), {"voltage": 1.5e-3}),
        },
    ),
    CurrentSource: (
        check_current_source,
        {
            **SUPPLY_CHANNELS,
            "sim sis ctrl": lambda: SimSisBlock().ctrl("DEV3"),
            "sis ctrl": lambda: sis().ctrl("DEV3"),
        },
    ),
    VoltageCurrentMeter: (
        check_voltage_current_meter,
        {
            **SUPPLY_CHANNELS,
            "sim sis bias": lambda: SimSisBlock().channel("DEV2"),
            "sis bias": lambda: sis().channel("DEV2"),
        },
    ),
    FrequencySource: (
        check_frequency_source,
        {"sim signal generator": SimSignalGenerator, "agilent": agilent},
    ),
    PowerLevel: (
        check_power_level,
        {"sim signal generator": SimSignalGenerator, "agilent": agilent},
    ),
    PowerDetector: (
        check_power_detector,
        {"sim power meter": SimPowerMeter, "nrx": nrx},
    ),
    TunableFilter: (
        check_tunable_filter,
        {
            "sim yig filter": lambda: SimYigFilter().channel("yig_1"),
            "yig": lambda: yig().channel("yig_2"),
        },
    ),
    LoadSwitch: (check_load_switch, {"sim chopper": SimChopper, "chopper": chopper}),
}


def contract_cases():
    """(id, capability, check, factory, check kwargs); a factory may come with kwargs."""
    for capability, (check, factories) in CONTRACTS.items():
        for label, factory in factories.items():
            factory, kwargs = factory if isinstance(factory, tuple) else (factory, {})
            yield f"{capability.__name__}-{label}", capability, check, factory, kwargs
