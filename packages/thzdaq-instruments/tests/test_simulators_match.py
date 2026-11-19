"""A simulator offers what its driver does: a measurement, a dock or a script
checked on the simulator works the same on the instrument.

Compared part by part (the instrument, its channels, each sub-device part):
capabilities, quantity keys, action keys. How an instrument is reached (ACCESS:
Identifiable, RawCommands) may be more on the simulator: one simulator serves
several drivers (SimCompressor the F-70 over RS-232 and over REST), and the
station allows raw commands only when the driver and the opened class both
take them.
"""

import pytest
from thzdaq_instruments.capabilities import ACCESS, capabilities_of
from thzdaq_instruments.drivers import DRIVERS
from thzdaq_instruments.parts import actions_for, quantities_for

PAIRS = [(driver, sim) for driver, _, sim in DRIVERS if sim is not None]


def parts(cls):
    """The classes of what an instrument class offers as devices, by role."""
    found = {"instrument": cls}
    if cls.channel_class is not None:
        found["channel"] = cls.channel_class
    for key, sub in cls.subdevices.items():
        if sub.part_class is not None:
            found[f"subdevice {key}"] = sub.part_class
    return found


def offered(cls):
    capabilities = capabilities_of(cls)
    quantities = quantities_for(capabilities, getattr(cls, "quantities", ()))
    actions = actions_for(capabilities, getattr(cls, "actions", ()))
    return (
        set(capabilities),
        {q.key for q in quantities},
        {a.key for a in actions},
    )


@pytest.mark.parametrize(
    "driver, sim", PAIRS, ids=[driver.__name__ for driver, _ in PAIRS]
)
def test_simulator_offers_what_its_driver_does(driver, sim):
    assert set(sim.subdevices) == set(driver.subdevices)
    driver_parts, sim_parts = parts(driver), parts(sim)
    assert set(sim_parts) == set(driver_parts)
    for role, part in driver_parts.items():
        capabilities, quantities, actions = offered(part)
        sim_capabilities, sim_quantities, sim_actions = offered(sim_parts[role])
        access = set(ACCESS)
        assert sim_capabilities - access == capabilities - access, role
        assert capabilities & access <= sim_capabilities, role
        assert sim_quantities == quantities, role
        assert sim_actions == actions, role
