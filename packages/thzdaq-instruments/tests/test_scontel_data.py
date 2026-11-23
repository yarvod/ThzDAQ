"""A bias and a coil of the SIS block are read with one DATA? query: what a
procedure measures and what a monitor or a dock polls together."""

import pytest
from emulators import SisEmulator
from thzdaq_instruments.drivers import ScontelSisBlock
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.parts import quantities_of, read_values


def block(emulator=None, **offsets):
    emulator = emulator or SisEmulator()
    transport, link = emulator.transport()
    return ScontelSisBlock(transport, offsets=offsets), emulator, link


def queries(link):
    return [line for kind, line in link.events if kind == "w"]


def test_a_measure_is_one_query_with_the_offsets_applied():
    sis, emulator, link = block(DEV4=(0.1e-3, 2e-6))
    emulator.setpoints["DEV4"] = 2e-3
    reading = sis.channel("DEV4").measure()
    assert queries(link) == ["BIAS:DEV4:DATA?"]
    assert reading.voltage == pytest.approx(2e-3 + 0.1e-3)
    assert reading.current == pytest.approx(2e-3 / 20 + 2e-6)


def test_a_bias_polled_whole_is_one_query():
    sis, emulator, link = block()
    emulator.setpoints["DEV4"] = 1e-3
    emulator.shorts["BIAS:DEV4"] = "0"
    bias = sis.channel("DEV4")
    measured = [q for q in quantities_of(bias) if q.key != "voltage_set"]
    values = read_values(bias, measured)
    assert queries(link) == ["BIAS:DEV4:DATA?"]
    assert values == {
        "voltage": pytest.approx(1e-3),
        "current": pytest.approx(1e-3 / 20),
        "active": True,
    }


def test_a_coil_polled_whole_is_one_query():
    sis, emulator, link = block()
    emulator.ctrl["DEV3"] = 7e-3
    coil = sis.ctrl("DEV3")
    measured = [q for q in quantities_of(coil) if q.key != "current_set"]
    values = read_values(coil, measured)
    assert queries(link) == ["CTRL:DEV3:DATA?"]
    assert values == {"coil_current": pytest.approx(7e-3), "active": False}


def test_a_coil_tells_the_current_set_without_asking():
    sis, _, link = block()
    coil = sis.ctrl("DEV3")
    assert coil.get_current() == 0.0  # none set yet: read once
    coil.set_current(12.5e-3)
    asked = len(queries(link))
    assert coil.get_current() == 12.5e-3
    assert len(queries(link)) == asked


def test_an_answer_that_does_not_parse_is_asked_again():
    emulator = SisEmulator()
    emulator.garbled = 1
    sis, _, link = block(emulator)
    assert sis.channel("DEV4").read_data().active is False
    assert queries(link) == ["BIAS:DEV4:DATA?"] * 2


def test_answers_that_never_parse_fail():
    emulator = SisEmulator()
    emulator.garbled = 3
    sis, _, _ = block(emulator)
    with pytest.raises(InstrumentResponseError, match="DATA"):
        sis.channel("DEV4").measure()
