"""A device as the station hands it out (a port over its part) offers what the
part does: its quantities and actions, whatever wraps it."""

import time

import pytest
from thzdaq_core.domain.station.config import (
    DeviceConfig,
    InstrumentConfig,
    StationConfig,
)
from thzdaq_core.domain.station.ports import PortAdapter
from thzdaq_core.domain.station.station import Station
from thzdaq_instruments.parts import actions_of, quantities_of
from thzdaq_instruments.sim import SimPowerMeter

# A device, and the part of its instrument it is
PARTS = {
    "meter": lambda station: station.instrument("meter"),
    "supply:1": lambda station: station.instrument("supply").channel(1),
    "chopper": lambda station: station.instrument("chopper"),
    # a configured device: its attributes (SIS offsets) wrap the channel too
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
            "supply": InstrumentConfig("sim.power_supply"),
            "chopper": InstrumentConfig("sim.chopper"),
            "sis": sis,
        },
    )
    with Station(config, pause=time.sleep) as station:
        yield station


@pytest.mark.parametrize("ref", sorted(PARTS))
def test_a_guarded_device_offers_what_its_part_does(station, ref):
    device, part = station.device(ref), PARTS[ref](station)
    assert keys(quantities_of(part))
    assert keys(quantities_of(device)) == keys(quantities_of(part))
    assert keys(actions_of(device)) == keys(actions_of(part))


def test_an_adapter_offers_what_it_wraps():
    meter = SimPowerMeter()
    assert "power" in keys(quantities_of(PortAdapter(meter)))
    assert keys(quantities_of(PortAdapter(meter))) == keys(quantities_of(meter))
