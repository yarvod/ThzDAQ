"""Passports of drivers: what an instrument accepts at all, by quantity key."""

import pytest
from emulators import RigolEmulator
from thzdaq_instruments.drivers import DRIVERS, AgilentE8247C, RigolDP832A
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import (
    CURRENT_SET,
    POWER_LEVEL,
    VOLTAGE_SET,
    Quantity,
    quantities_for,
)
from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.sim import SimSisBlock


def test_a_limit_says_what_is_wrong():
    limit = Limit(0.0, 30.0)
    assert limit.problem(12.0) is None
    assert limit.problem(31.0, "V") == "above 30 V"
    assert limit.problem(-1.0, "V") == "below 0 V"
    assert Limit(maximum=25.0).problem(-130.0) is None


def test_a_channel_may_differ_from_the_others():
    assert RigolDP832A.passport(1)[VOLTAGE_SET.key] == Limit(0.0, 30.0)
    assert RigolDP832A.passport(3)[VOLTAGE_SET.key] == Limit(0.0, 5.0)
    assert AgilentE8247C.passport()[POWER_LEVEL.key].maximum == 25.0
    assert SimSisBlock.passport("DEV4") == {}  # the range of a DEV is not known yet


@pytest.mark.parametrize(
    "cls", [cls for cls, _, _ in DRIVERS], ids=lambda c: c.__name__
)
def test_a_passport_names_settable_numbers_of_the_driver(cls):
    parts = [cls] + ([cls.channel_class] if cls.channel_class else [])
    settable = {
        q.key
        for part in parts
        for q in quantities_for(capabilities_of(part), getattr(part, "quantities", ()))
        if q.settable and q.kind in ("float", "int")
    }
    passports = [cls.limits, *cls.channel_limits.values()]
    assert all(set(passport) <= settable for passport in passports)


def test_setpoints_name_the_methods_that_set_them():
    channel = SimSisBlock().channel("DEV4")
    by_key = {
        q.key: q
        for q in quantities_for(capabilities_of(type(channel)), channel.quantities)
    }
    assert by_key[VOLTAGE_SET.key].setters == ("set_voltage", "set_voltage_precise")
    by_key[VOLTAGE_SET.key].write(channel, "2 mV")
    assert channel.get_voltage() == pytest.approx(2e-3)
    assert by_key["active"].danger  # shorting a biased junction may damage it


def test_a_quantity_refuses_a_value_outside_its_range():
    multiplier = Quantity(
        "multiplier", "Multiplier", setters=("x",), minimum=1, maximum=100
    )
    assert multiplier.parse("12") == 12.0
    for bad in (0.5, 101):
        with pytest.raises(ValueError):
            multiplier.parse(bad)


def test_the_rigol_protects_its_outputs():
    emulator = RigolEmulator()
    supply = RigolDP832A(emulator.transport()[0])
    supply.channel(2).set_protection(12.0, 0.5)
    supply.channel(3).set_protection(None, 0.2)
    channels = emulator.channels
    assert channels[2].protection == {"OVP": (12.0, True), "OCP": (0.5, True)}
    assert channels[3].protection == {"OCP": (0.2, True)}
    assert not emulator.errors
    assert CURRENT_SET.key in RigolDP832A.passport(3)
