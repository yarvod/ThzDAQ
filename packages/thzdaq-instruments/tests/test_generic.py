"""Instruments without a driver: the generic driver, its simulator, and a
connection written as one line."""

import pytest
from emulators import GaugeEmulator
from thzdaq_instruments import default_registry
from thzdaq_instruments.capabilities import ACCESS, capabilities_of
from thzdaq_instruments.drivers import GenericScpi
from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import GENERIC
from thzdaq_instruments.quantities import quantities_of
from thzdaq_instruments.sim import SimGenericScpi
from thzdaq_instruments.transport import (
    PROLOGIX,
    SERIAL,
    SOCKET,
    VISA,
    ConnectionSpec,
    connection_url,
    parse_connection,
)


def test_a_generic_instrument_only_takes_raw_commands():
    assert set(capabilities_of(GenericScpi)) <= set(ACCESS)
    assert not quantities_of(GenericScpi(GaugeEmulator().transport()[0]))
    assert not quantities_of(SimGenericScpi())
    info = default_registry().get(GenericScpi.driver_key)
    assert info.device_type == GENERIC and info.sim is SimGenericScpi


def test_its_commands_go_as_typed():
    emulator = GaugeEmulator()
    transport, link = emulator.transport()
    gauge = GenericScpi(transport)
    assert gauge.send_raw("PR1?", True) == "P=1.200E-03"
    assert gauge.send_raw("VOLT 2.5", False) is None
    assert gauge.send_raw("VOLT?", True) == "2.500000"
    assert link.written == ["PR1?", "VOLT 2.5", "VOLT?"] and not emulator.errors


def test_its_simulator_answers_a_query_with_what_was_written():
    gauge = SimGenericScpi(name="gauge_1")
    assert gauge.send_raw("volt 2.500000", False) is None
    assert gauge.send_raw("VOLT?", True) == "2.500000"
    assert gauge.send_raw("*IDN?", True) == gauge.identify()
    gauge.send_raw("*CLS", False)  # taken, nothing to remember
    with pytest.raises(InstrumentResponseError, match="nothing was written to PR1"):
        gauge.send_raw("PR1?", True)
    assert gauge.send_raw("OUTP ON", True) == ""  # a write read back answers nothing


@pytest.mark.parametrize(
    "text, spec",
    [
        ("tcp://169.254.0.50:5025", ConnectionSpec(SOCKET, "169.254.0.50", 5025)),
        (
            "prologix://169.254.156.103/19",
            ConnectionSpec(PROLOGIX, "169.254.156.103", gpib=19),
        ),
        (
            "serial://COM3?baudrate=115200",
            ConnectionSpec(SERIAL, serial_port="COM3", baudrate=115200),
        ),
        ("serial:///dev/ttyUSB0", ConnectionSpec(SERIAL, serial_port="/dev/ttyUSB0")),
        ("visa://GPIB0::19::INSTR", ConnectionSpec(VISA, resource="GPIB0::19::INSTR")),
        (
            "tcp://h:1?timeout=5&write_termination=%0D&read_termination=none",
            ConnectionSpec(
                SOCKET, "h", 1, timeout=5.0, write_termination="\r",
                read_termination=None,
            ),  # fmt: skip
        ),
    ],
)
def test_a_connection_is_one_line(text, spec):
    assert parse_connection(text) == spec
    assert parse_connection(connection_url(spec)) == spec
    assert connection_url(parse_connection(text)).startswith(text.partition("?")[0])


@pytest.mark.parametrize(
    "text, told",
    [
        ("169.254.0.50:5025", "is no connection"),
        ("ftp://host", "is no connection"),
        ("tcp://host", "requires port"),
        ("prologix://169.254.156.103", "GPIB address after /"),
        ("tcp://host:5025?speed=1", "no connection field speed"),
        ("tcp://host:port", "invalid literal"),
    ],
)
def test_a_wrong_line_says_how_to_write_it(text, told):
    with pytest.raises(ConfigurationError, match=told):
        parse_connection(text)
