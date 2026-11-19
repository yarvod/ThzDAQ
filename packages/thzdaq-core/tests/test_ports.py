"""A device as the station hands it out (a port over its part) offers what the
part declares: its capabilities, their quantities and actions, and nothing else;
every setter a capability declares goes through the guard."""

import time
from abc import abstractmethod

import pytest
from thzdaq_core.domain.station import ports
from thzdaq_core.domain.station.config import (
    DeviceConfig,
    InstrumentConfig,
    StationConfig,
)
from thzdaq_core.domain.station.ports import GuardedPort, port_class
from thzdaq_core.domain.station.safety import Guard, SafetyLimit
from thzdaq_core.domain.station.station import Station
from thzdaq_instruments.actions import ZERO_SENSOR
from thzdaq_instruments.capabilities import (
    ALL_CAPABILITIES,
    Capability,
    PowerDetector,
    PreciseVoltageSource,
    VoltageSource,
    capabilities_of,
)
from thzdaq_instruments.errors import LimitError
from thzdaq_instruments.parts import actions_of, quantities_of
from thzdaq_instruments.quantities import AVERAGING, CORRECTION_FREQUENCY
from thzdaq_instruments.sim import SimPowerMeter

# A device, and the part of its instrument it is
PARTS = {
    "meter": lambda station: station.instrument("meter"),
    "supply:1": lambda station: station.instrument("supply").channel(1),
    "chopper": lambda station: station.instrument("chopper"),
    # a configured device: its attributes (SIS offsets) are set on the channel
    "sis_bias_1": lambda station: station.instrument("sis").channel("DEV4"),
}


def keys(items):
    return [item.key for item in items]


@pytest.fixture
def station():
    sis = InstrumentConfig("sim.sis_block")
    sis.devices["sis_bias_1"] = DeviceConfig(kind="sis_bias", channel="DEV4")
    config = StationConfig(
        name="ports",
        instruments={
            "meter": InstrumentConfig("sim.power_meter"),
            "sensor": InstrumentConfig("keysight.u2002h", simulate=True),
            "supply": InstrumentConfig("sim.power_supply"),
            "chopper": InstrumentConfig("sim.chopper"),
            "generator": InstrumentConfig("sim.signal_generator"),
            "sis": sis,
        },
    )
    with Station(config, pause=time.sleep) as station:
        yield station


@pytest.mark.parametrize("ref", sorted(PARTS))
def test_a_guarded_device_offers_what_its_part_does(station, ref):
    device, part = station.device(ref), PARTS[ref](station)
    assert device.target is part
    assert keys(quantities_of(part))
    assert keys(quantities_of(device)) == keys(quantities_of(part))
    assert keys(actions_of(device)) == keys(actions_of(part))
    assert capabilities_of(type(device)) == capabilities_of(type(part))


def test_a_port_is_its_capabilities_by_declaration():
    meter = SimPowerMeter()
    device = port_class(SimPowerMeter)(meter, Guard("meter", {}, {}), (), time.sleep)
    assert isinstance(device, PowerDetector) and not isinstance(device, VoltageSource)
    assert "power" in keys(quantities_of(device))
    assert keys(quantities_of(device)) == keys(quantities_of(meter))
    assert port_class(SimPowerMeter) is type(device)  # built once


@pytest.mark.parametrize(
    "ref, undeclared",
    [
        ("meter", "fetch"),  # a power meter's own reading
        ("meter", "set_averaging"),  # its own configuration
        ("sensor", "set_frequency"),  # a sensor's correction: no FrequencySource
        ("sensor", "zero"),  # its own action
        ("generator", "set_frequency_multiplier"),
        ("sis_bias_1", "write_calibration"),
        ("sis_bias_1", "offset_voltage"),  # an attribute of the configured device
        ("chopper", "start_rotation"),
    ],
)
def test_what_no_capability_declares_is_not_on_the_port(station, ref, undeclared):
    device = station.device(ref)
    assert hasattr(device.target, undeclared)
    assert not hasattr(device, undeclared)
    with pytest.raises(AttributeError):
        getattr(device, undeclared)


class Refusing:
    """A guard that takes no value: what reaches it never reaches the part."""

    def check(self, quantity, value):
        raise LimitError(f"{quantity.key} refused")


def everything() -> type:
    """A part class with every capability (the most refined of each line)."""
    bases = tuple(
        c
        for c in ALL_CAPABILITIES
        if not any(o is not c and issubclass(o, c) for o in ALL_CAPABILITIES)
    )
    return type("Everything", bases, {})


SETTERS = sorted(
    (capability.__name__, quantity, name)
    for capability in ALL_CAPABILITIES
    for quantity in capability.capability_quantities
    for name in quantity.setters
)


@pytest.mark.parametrize(
    "capability, quantity, setter",
    SETTERS,
    ids=[f"{c}.{name}" for c, _, name in SETTERS],
)
def test_every_setter_a_capability_declares_goes_through_the_guard(
    capability, quantity, setter
):
    cls = everything()
    part = object()  # nothing may reach it
    device = port_class(cls)(part, Refusing(), [quantity], time.sleep)
    with pytest.raises(LimitError, match=f"{quantity.key} refused"):
        getattr(device, setter)(1.0)


def test_every_capability_method_reaches_the_part():
    calls = []

    class Part:
        def __getattr__(self, name):
            return lambda *args, **kwargs: calls.append(name)

    cls = everything()
    device = port_class(cls)(Part(), Guard("all", {}, {}), (), time.sleep)
    names = sorted({n for c in ALL_CAPABILITIES for n in c.__abstractmethods__})
    for name in names:
        getattr(device, name)(*([0.0] * _arguments(cls, name)))
    assert calls == names


def _arguments(cls, name) -> int:
    code = getattr(cls, name).__code__
    defaults = getattr(cls, name).__defaults__ or ()
    return code.co_argcount - 1 - len(defaults)


def test_a_precise_bias_is_guarded_as_its_setpoint(station):
    bias = station.device("sis_bias_1")
    assert isinstance(bias, PreciseVoltageSource)
    limited = Guard("sis_bias_1", {}, {"voltage_set": SafetyLimit(maximum=1e-3)})
    port = type(bias)(bias.target, limited, bias.setters.values(), time.sleep)
    with pytest.raises(LimitError, match="voltage_set"):
        port.set_voltage_precise(2e-3, max_iterations=1)
    port.set_voltage_precise(0.5e-3, max_iterations=1)
    assert bias.target.get_voltage() == pytest.approx(0.5e-3)


def test_own_quantities_and_actions_are_reached_by_declaration(station):
    sensor = station.device("sensor")
    sensor.write(AVERAGING, False)
    assert sensor.read([AVERAGING]) == {"averaging": False}
    sensor.act(ZERO_SENSOR, {})
    # The correction frequency is a setpoint of the sensor's own: guarded too
    assert CORRECTION_FREQUENCY in sensor.setters.values()
    limited = Guard("sensor", {}, {"frequency": SafetyLimit(maximum=1e9)})
    port = type(sensor)(sensor.target, limited, [CORRECTION_FREQUENCY], time.sleep)
    with pytest.raises(LimitError, match="frequency"):
        port.write(CORRECTION_FREQUENCY, 2e9)
    port.write(CORRECTION_FREQUENCY, 0.5e9)
    assert sensor.target.get_frequency() == pytest.approx(0.5e9)


def test_a_capability_method_may_not_hide_the_port(monkeypatch):
    class Forgetful(Capability):
        @abstractmethod
        def forget(self) -> None:
            """A name of the port itself: its setpoints are not known."""

    class Part(Forgetful):
        def forget(self) -> None:
            ...

    monkeypatch.setattr(ports, "capabilities_of", lambda cls: (Forgetful,))
    with pytest.raises(TypeError, match="Forgetful.forget"):
        port_class(Part)


def test_a_port_is_a_guarded_port(station):
    assert all(isinstance(station.device(ref), GuardedPort) for ref in PARTS)
