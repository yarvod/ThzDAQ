"""A console of a window: its kernel calls as console, with the rights of a
person's script. What a person does in a dock goes at once; what a dock
confirms (a value beyond the warn range, a dangerous step, a raw write, a
change of the profile) waits for a person in a window (contract: LocalLab and
RemoteLab)."""

import copy

import pytest
from lab_helpers import Window, calling
from thzdaq_api.devices import RawCommand, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import WaitMeasurement
from thzdaq_api.origins import CONSOLE, CONSOLE_CLIENT, GUI, agent, scripted
from thzdaq_api.sessions import EndSession, RestoreOnExit, StartSession
from thzdaq_api.station import GetStation, UpdateStation

LIMITS = {"sis_bias_1": {"voltage_set": {"min": -5e-3, "max": 5e-3, "warn_max": 4e-3}}}


def bias(value):
    return SetQuantity(ref="sis_bias_1", key="voltage_set", value=value)


@pytest.fixture
def bias_warns(lab):
    """sis_bias_1 warns above 4 mV."""
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"limits": LIMITS}
    lab.call(UpdateStation(profile=profile))
    return lab


@pytest.fixture
def console(lab_as):
    return lab_as(CONSOLE, CONSOLE_CLIENT)


def denied(console, operation):
    """Nobody answers: what waits for a person is refused at once."""
    with pytest.raises(LabError) as caught:
        console.call(operation)
    assert caught.value.code == ErrorCode.DENIED, operation


def test_a_console_is_a_persons_code():
    assert scripted(CONSOLE) and not agent(CONSOLE)


def test_what_a_dock_does_goes_at_once(bias_warns, console):
    assert console.call(bias("1mV")).value == pytest.approx(1e-3)
    query = RawCommand(instrument="signal_generator_1", command="*IDN?")
    assert console.call(query).answer
    session = console.call(StartSession(title="look", devices=("sis_bias_1",)))
    console.call(RestoreOnExit(id=session.id, ref="sis_bias_1", key="voltage_set"))
    console.call(bias("2mV"))
    ended = console.call(EndSession(id=session.id))
    assert ended.status == "completed"
    assert console.call(bias("1mV")).value == pytest.approx(1e-3)


def test_what_a_dock_confirms_waits_for_a_person(bias_warns, console):
    for operation in (
        bias("4.5mV"),  # beyond the warn range
        SetQuantity(ref="sis_bias_1", key="active", value=False),  # dangerous
        RawCommand(instrument="signal_generator_1", command="OUTP ON"),
        UpdateStation(profile=bias_warns.call(GetStation()).profile),
    ):
        denied(console, operation)


def test_a_person_in_the_window_allows_it(bias_warns, console, lab_as):
    window = Window(lab_as(GUI))
    try:
        thread, done = calling(console, bias("4.5mV"))
        assert "above warn_max 4 mV" in window.asked().warning
        window.answer(allowed=True)
        thread.join(5)
        assert done["result"].value == pytest.approx(4.5e-3)
    finally:
        window.stop()


def test_a_session_of_a_console_is_its_own(console, lab_as):
    session = console.call(StartSession(title="look"))
    other = lab_as("script:scan", "script")
    with pytest.raises(LabError) as caught:
        other.call(EndSession(id=session.id))
    assert caught.value.code == ErrorCode.DENIED
    console.call(EndSession(id=session.id))
    assert console.call(WaitMeasurement(id=session.id)).status == "completed"
