"""An instrument a script declares: its raw commands named as values, read
and written through the bench's raw commands (thzdaq_api.raw)."""

import pytest
from thzdaq_api.data import Measured
from thzdaq_api.devices import DeviceDescription, DeviceInfo
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Readout
from thzdaq_api.raw import RawInstrument, named_values, reading, setting


class Bench:
    """A generic instrument's bench: no quantities of its own; answers raw
    queries from answers, keeps the writes."""

    def __init__(self, **answers):
        self.answers = answers
        self.written = []

    def describe(self, ref):
        info = DeviceInfo(ref, ref, ref, "generic.scpi", "instrument", "generic", ())
        return DeviceDescription(info, (), ())

    def read(self, ref, *keys, display=False):
        return Readout()

    def raw(self, instrument, command, answer=False):
        if "?" in command:
            return self.answers[command]
        self.written.append(command)
        return None


def gauge(bench, **named):
    return RawInstrument(bench, "gauge_1", named_values(named))


@pytest.mark.parametrize(
    "parse, answer, value",
    [
        (None, " 2.500000\n", 2.5),
        (r"P=([0-9.Ee+-]+)", "P=1.20E+00 mbar", 1.2),
        (r"[0-9.]+", "about 7.5 Pa", 7.5),  # no group: what it matches
        ({"ON": True, "OFF": False}, "on", True),
        (lambda text: float(text.split(",")[1]), "1.0,3.5,0", 3.5),
    ],
)
def test_an_answer_is_parsed_as_the_reading_says(parse, answer, value):
    found = gauge(Bench(**{"Q?": answer}), x=reading("Q?", parse=parse)).x
    assert found == value


def test_a_number_read_is_si_with_its_unit_and_source():
    bench = Bench(**{"PR1?": "P=1.20E+00"})
    found = gauge(
        bench, pressure=reading("PR1?", unit="Pa", parse=r"P=(\S+)", scale=100)
    )
    pressure = found.pressure
    assert isinstance(pressure, Measured) and pressure == pytest.approx(120.0)
    assert (pressure.unit, pressure.source) == ("Pa", "gauge_1/pressure")
    assert found.read() == {"pressure": pressure}
    assert found.read(display=True) == {"pressure": "120 Pa"}
    assert found["pressure"] == pressure


def test_an_answer_that_reads_as_no_value_says_how_to_parse_it():
    with pytest.raises(LabError) as caught:
        gauge(Bench(**{"PR1?": "P=?"}), p=reading("PR1?", parse=r"P=(\d+)")).p
    assert caught.value.code == ErrorCode.INSTRUMENT
    assert "gauge_1/p" in caught.value.message and "parse=" in caught.value.hint


def test_a_setting_writes_within_its_limits_and_reads_back():
    bench = Bench(**{"VOLT?": "2.500000"})
    found = gauge(
        bench,
        level=setting("VOLT?", "VOLT {:.6f}", unit="V", minimum=0, maximum=5),
        current=setting(None, "CURR {:.3f}", unit="A", scale=1e-3),  # in mA
        heater=setting("HT?", "HT {}", parse={"1": True, "0": False}),
    )
    found.level = 2.5
    found["level"] = Measured(1.0, "V")
    found.current = 0.002
    found.heater = False
    assert bench.written == ["VOLT 2.500000", "VOLT 1.000000", "CURR 2.000", "HT 0"]
    assert found.level == 2.5
    with pytest.raises(LabError) as beyond:
        found.level = 25  # 2.5 mistyped: never sent
    assert beyond.value.code == ErrorCode.OUT_OF_LIMITS
    assert "25 V is beyond 0..5 V" in beyond.value.message
    with pytest.raises(LabError) as written_only:
        found.current
    assert written_only.value.code == ErrorCode.NOT_ALLOWED
    with pytest.raises(LabError) as text:
        found.level = "2.5 V"
    assert text.value.code == ErrorCode.INVALID_ARGUMENTS
    assert len(bench.written) == 4


def test_a_reading_is_not_written_and_only_readings_are_named():
    bench = Bench()
    found = gauge(bench, p=reading("PR1?"))
    with pytest.raises(LabError) as caught:
        found.p = 1.0
    assert caught.value.code == ErrorCode.NOT_ALLOWED and not bench.written
    with pytest.raises(TypeError, match="reading"):
        named_values({"p": "PR1?"})
    assert {"p", "raw"} <= set(dir(found))
