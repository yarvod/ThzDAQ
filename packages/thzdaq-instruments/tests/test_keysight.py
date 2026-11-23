import pytest
from emulators import U2000Emulator
from thzdaq_instruments.capabilities import (
    Identifiable,
    PowerDetector,
    RawCommands,
    capabilities_of,
)
from thzdaq_instruments.drivers import KeysightU2002H
from thzdaq_instruments.errors import ConfigurationError, InstrumentError
from thzdaq_instruments.parts import actions_of, quantities_of
from thzdaq_instruments.sim import SimU2000
from thzdaq_instruments.transport.base import VISA


def sensor(emulator=None):
    emulator = emulator or U2000Emulator()
    transport, link = emulator.transport()
    return KeysightU2002H(transport), emulator, link


def test_it_is_a_power_detector_and_nothing_else():
    assert set(capabilities_of(KeysightU2002H)) == {
        PowerDetector, Identifiable, RawCommands,
    }  # fmt: skip


def test_it_is_reached_over_visa():
    spec = KeysightU2002H.connection("USB0::0x0957::0x2F18::MY54260001::0::INSTR")
    assert spec.kind == VISA and spec.timeout == 20.0


def test_setup_is_offered_its_timeout_without_a_resource():
    # A reading waits for the averaging filter: the default 2 s timed it out
    assert KeysightU2002H.recommended_connection() == {"kind": VISA, "timeout": 20.0}


def test_the_constructor_writes_nothing():
    _, _, link = sensor()
    assert link.written == []


def test_identifies_its_model():
    meter, emulator, _ = sensor()
    assert meter.test()
    assert emulator.errors == []


def test_a_reading_is_dbm_and_single_whatever_was_set_before():
    meter, emulator, _ = sensor(U2000Emulator(power_dbm=-23.5))
    meter.send_raw("UNIT:POW W", False)
    meter.send_raw("INIT:CONT ON", False)
    assert meter.read_power() == pytest.approx(-23.5)
    assert emulator.unit == "DBM" and not emulator.continuous
    assert emulator.queue == [] and emulator.errors == []


def test_frequency_temperature_offset():
    meter, emulator, _ = sensor()
    meter.set_frequency(6e9)
    assert emulator.frequency == 6e9 and meter.get_frequency() == 6e9
    assert meter.read_temperature() == pytest.approx(300.15)
    assert meter.get_offset() == 0.0  # off after *RST
    meter.set_offset(-10.0)
    assert meter.get_offset() == -10.0
    assert meter.read_power() == pytest.approx(-30.0)
    assert emulator.errors == []


def test_measurement_rate():
    meter, emulator, _ = sensor()
    meter.set_measurement_rate("DOUB")
    assert meter.get_measurement_rate() == "DOUB"
    with pytest.raises(ConfigurationError):
        meter.set_measurement_rate("SLOW")
    assert emulator.errors == []


def test_settings_are_written_in_the_order_the_sensor_couples_them():
    """As the station writes a profile's settings on open: in quantity order.
    A count turns auto off and averaging on, auto turns averaging on: written
    count, auto, averaging, the profile's values stay."""
    meter, emulator, _ = sensor()
    profile = {
        "averaging": False, "averaging_auto": True, "averaging_count": 64,
        "measurement_rate": "FAST", "offset": 3.0,
    }  # fmt: skip
    for quantity in quantities_of(meter):
        if quantity.persistent and quantity.key in profile:
            quantity.write(meter, profile[quantity.key])
    assert (emulator.averaging_count, emulator.averaging_auto, emulator.averaging) == (
        64, True, False,
    )  # fmt: skip
    read = {q.key: q.read(meter) for q in quantities_of(meter) if q.key in profile}
    assert read == profile


def test_settings_are_configuration_and_frequency_a_setpoint():
    meter, _, _ = sensor()
    quantities = {q.key: q for q in quantities_of(meter)}
    assert [k for k, q in quantities.items() if q.persistent] == [
        "averaging_count", "averaging_auto", "averaging", "measurement_rate", "offset",
    ]  # fmt: skip
    assert quantities["frequency"].setters == ("set_frequency",)
    assert KeysightU2002H.passport()["frequency"].problem(30e9, "Hz")
    assert not KeysightU2002H.keeps_settings


@pytest.mark.parametrize("zero, kind", [("zero", "INT"), ("zero_external", "EXT")])
def test_zero(zero, kind):
    meter, emulator, link = sensor()
    getattr(meter, zero)()
    assert emulator.zeros == [kind]
    assert link.written[:4] == [
        "*CLS", f"CAL:ZERO:TYPE {kind}", "CAL:ZERO:AUTO ONCE", "*OPC?",
    ]  # fmt: skip
    assert emulator.errors == []


def test_a_failed_zero_raises():
    emulator = U2000Emulator()
    emulator.zero_fails = True
    meter, _, _ = sensor(emulator)
    with pytest.raises(InstrumentError, match="-231"):
        meter.zero()


def test_errors_reads_the_queue_until_it_is_empty():
    meter, emulator, _ = sensor()
    emulator.queue.extend(['-113,"Undefined header"', '-221,"Settings conflict"'])
    assert meter.errors() == ['-113,"Undefined header"', '-221,"Settings conflict"']
    assert meter.errors() == []


def test_actions_zero_the_sensor():
    meter, _, _ = sensor()
    actions = {a.key: a for a in actions_of(meter)}
    assert list(actions) == ["zero", "zero_external"]
    assert actions["zero_external"].danger and not actions["zero"].danger


class TestSimulator:
    def test_offset_adds_to_the_power(self):
        meter = SimU2000(power=-20.0)
        meter.set_offset(-10.0)
        assert meter.read_power() == pytest.approx(-30.0)

    def test_averaging_couples_as_the_sensors(self):
        meter = SimU2000()
        meter.set_averaging(False)
        meter.set_averaging_count(16)
        assert (meter.get_averaging_auto(), meter.get_averaging()) == (False, True)
        meter.set_averaging(False)
        meter.set_averaging_auto(True)
        assert meter.get_averaging()

    def test_zero_does_nothing(self):
        meter = SimU2000(power=-20.0)
        meter.zero()
        meter.zero_external()
        assert meter.read_power() == pytest.approx(-20.0)
