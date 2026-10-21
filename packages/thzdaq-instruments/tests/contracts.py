"""Behaviour every implementation of a capability must have (LSP).

Factories create a fresh instrument or channel. Real drivers join these lists
with a FakeLink-backed transport, so drivers and simulators pass the same checks.
"""

import math

from emulators import (
    AgilentEmulator,
    F70Emulator,
    FakeJsonClient,
    FsekEmulator,
    HmpEmulator,
    KeithleyEmulator,
    LakeShoreEmulator,
    MotorRegisters,
    NrxEmulator,
    PfeifferBus,
    RigolEmulator,
    SisEmulator,
    Sr830Emulator,
    ZvaEmulator,
)
from thzdaq_instruments.capabilities import (
    Compressor,
    CurrentSource,
    FrequencySource,
    Identifiable,
    LoadSwitch,
    NetworkAnalyzer,
    PowerDetector,
    PowerLevel,
    Rotator,
    SpectrumAnalyzer,
    Switchable,
    Thermometer,
    TunableFilter,
    VacuumGauge,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.drivers import (
    AgilentE8247C,
    ArduinoGrid,
    Keithley2200,
    LakeShore336,
    ModbusChopper,
    NiYigFilter,
    PfeifferGauge,
    PfeifferTurboPump,
    RigolDP832A,
    RohdeSchwarzFSEK30,
    RohdeSchwarzHMP2030,
    RohdeSchwarzNRX,
    RohdeSchwarzZVA67,
    ScontelSisBlock,
    StanfordSR830,
    SumitomoF70,
    SumitomoF70Rest,
)
from thzdaq_instruments.readings import ChannelReading, ComplexTrace, Trace
from thzdaq_instruments.sim import (
    SimChopper,
    SimCompressor,
    SimNetworkAnalyzer,
    SimPowerMeter,
    SimPowerSupply,
    SimRotator,
    SimSignalGenerator,
    SimSisBlock,
    SimSpectrumAnalyzer,
    SimTemperatureController,
    SimVacuumGauge,
    SimYigFilter,
)
from thzdaq_instruments.transport.base import MessageTransport
from thzdaq_instruments.transport.fake import FakeLink


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


def zva():
    return driver(RohdeSchwarzZVA67, ZvaEmulator())


def fsek():
    return driver(RohdeSchwarzFSEK30, FsekEmulator())


def lakeshore():
    return driver(LakeShore336, LakeShoreEmulator())


def sr830():
    return driver(StanfordSR830, Sr830Emulator())


def f70():
    return driver(SumitomoF70, F70Emulator())


class FakeF70Service(FakeJsonClient):
    def get(self, path):
        if "temperatures" in path:
            return {"temperatures": [22.0, 21.5, 20.0]}
        return {"pressures": [230.0]}


def f70_rest():
    return SumitomoF70Rest(client=FakeF70Service())


def pfeiffer_bus():
    link = FakeLink(
        PfeifferBus(
            {
                1: {309: "000820", 349: "TC 110", 340: "150016", 10: "000000"},
                2: {740: "250017", 349: "TPR280"},
            }
        )
    )
    link.open()
    return MessageTransport(link)


def tc110():
    return PfeifferTurboPump(pfeiffer_bus(), address=1)


def gauge():
    return PfeifferGauge(pfeiffer_bus(), address=2)


def grid():
    return ArduinoGrid(client=FakeJsonClient())


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


def check_thermometer(device):
    temperature = device.read_temperature()
    assert isinstance(temperature, float) and temperature > 0


def check_spectrum_analyzer(device):
    device.set_center_frequency(5e9)
    device.set_span(1e6)
    device.set_resolution_bandwidth(1e3)
    device.set_video_bandwidth(1e3)
    frequency, power = device.read_peak()
    assert isinstance(frequency, float) and isinstance(power, float)
    trace = device.read_trace()
    assert isinstance(trace, Trace) and len(trace.values) > 0


def check_network_analyzer(device):
    device.set_frequency_range(2e9, 12e9)
    device.set_points(11)
    device.select_parameter("S21")
    device.set_averaging(4)
    trace = device.read_trace()
    assert isinstance(trace, ComplexTrace) and len(trace.values) == 11
    assert trace.parameter == "S21"
    assert trace.frequency[0] == 2e9 and trace.frequency[-1] == 12e9


def check_vacuum_gauge(device):
    pressure = device.read_pressure()
    assert isinstance(pressure, float) and pressure > 0


def check_rotator(device):
    assert device.rotate_to(30.0) == 30.0
    assert device.get_angle() == 30.0


def check_compressor(device):
    device.turn_on()
    temperatures = device.read_temperatures()
    pressures = device.read_pressures()
    assert temperatures and all(isinstance(t, float) and t > 200 for t in temperatures)
    assert pressures and all(isinstance(p, float) for p in pressures)
    device.turn_off()


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
            "zva": zva,
            "fsek": fsek,
            "lakeshore": lakeshore,
            "sr830": sr830,
            "f70": f70,
            "f70 rest": f70_rest,
            "tc110": tc110,
            "gauge": gauge,
            "grid": grid,
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
        {
            "sim signal generator": SimSignalGenerator,
            "agilent": agilent,
            "sim network analyzer": SimNetworkAnalyzer,
            "zva": zva,
        },
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
    Thermometer: (
        check_thermometer,
        {
            "sim input": lambda: SimTemperatureController().channel("A"),
            "lakeshore input": lambda: lakeshore().channel("B"),
        },
    ),
    SpectrumAnalyzer: (
        check_spectrum_analyzer,
        {"sim spectrum analyzer": SimSpectrumAnalyzer, "fsek": fsek},
    ),
    NetworkAnalyzer: (
        check_network_analyzer,
        {"sim network analyzer": SimNetworkAnalyzer, "zva": zva},
    ),
    VacuumGauge: (
        check_vacuum_gauge,
        {"sim gauge": SimVacuumGauge, "gauge": gauge, "tc110": tc110},
    ),
    Rotator: (check_rotator, {"sim rotator": SimRotator, "grid": grid}),
    Compressor: (
        check_compressor,
        {"sim compressor": SimCompressor, "f70": f70, "f70 rest": f70_rest},
    ),
}


def contract_cases():
    """(id, capability, check, factory, check kwargs); a factory may come with kwargs."""
    for capability, (check, factories) in CONTRACTS.items():
        for label, factory in factories.items():
            factory, kwargs = factory if isinstance(factory, tuple) else (factory, {})
            yield f"{capability.__name__}-{label}", capability, check, factory, kwargs
