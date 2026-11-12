"""The assistant in the window is an agent: it looks freely, what it changes
waits for a person in the window, and it is refused what agents are refused
(contract: LocalLab and RemoteLab)."""

import pytest
from lab_helpers import Window, calling
from thzdaq_api.approvals import AnswerApproval
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.devices import ListDevices, RawCommand, SafeState, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.origins import ASSISTANT, ASSISTANT_CLIENT, GUI
from thzdaq_api.station import GetStation, UpdateStation


@pytest.fixture
def assistant(lab_as):
    return lab_as(ASSISTANT, ASSISTANT_CLIENT)


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def refused(lab, operation) -> LabError:
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    return caught.value


def test_the_assistant_looks_and_stops_without_a_person(assistant):
    assert assistant.call(ListDevices())
    assistant.call(SafeState())
    bias = SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV")
    denied = refused(assistant, bias)  # nobody in a window to allow it
    assert denied.code == ErrorCode.DENIED and "window" in denied.message


def test_what_the_assistant_sets_waits_for_the_person(assistant, window):
    thread, done = calling(
        assistant, SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV")
    )
    approval = window.asked()
    assert approval.origin == ASSISTANT
    window.answer(allowed=False, text="not now")
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    assert "not now" in str(done["error"])


def test_the_assistant_never_changes_the_profile_answers_or_writes_raw(
    assistant, window
):
    profile = assistant.call(GetStation()).profile
    for operation in (
        UpdateStation(profile=profile),
        AnswerApproval(id=1, allowed=True),
        RawCommand(instrument="sis_block_1", command="DEV4:OFF", share=True),
    ):
        assert refused(assistant, operation).code == ErrorCode.DENIED
    assert not window.waiting()


def test_a_listening_assistant_is_a_client_but_answers_nothing(assistant, lab_as):
    stop = assistant.subscribe(lambda event: None)
    try:
        clients = lab_as(GUI).call(GetDaemonStatus()).clients
        assert (ASSISTANT_CLIENT, ASSISTANT) in {(c.kind, c.origin) for c in clients}
        bias = SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV")
        assert refused(assistant, bias).code == ErrorCode.DENIED  # nobody answers
    finally:
        stop()
