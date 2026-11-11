"""What an agent changes waits for a person; people answer it (contract: LocalLab
and RemoteLab)."""

import pytest
from lab_helpers import Window, bodies, calling, wait_for
from thzdaq_api.approvals import AnswerApproval, AskUser, WaitAnswer
from thzdaq_api.devices import CallAction, ListDevices, SafeState, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ApprovalAnswered
from thzdaq_api.measurements import StartMeasurement
from thzdaq_api.origins import AGENT_CLI, ANSWERING_CLI, CLI, GUI
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.station import GetStation, UpdateStation

AGENT = "mcp:claude"
IV = dict(
    procedure=CURRENT_VS_VOLTAGE,
    parameters={
        "voltage": {"start": 0, "stop": 0.001, "points": 3},
        "settle_time": 0,
        "first_point_delay": 0,
    },
    devices={"bias": "sis_bias_1"},
)


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def test_an_agent_looks_and_stops_freely_and_never_changes_the_profile(lab_as):
    agent = lab_as(AGENT)
    assert agent.call(ListDevices())
    agent.call(SafeState())  # nobody to ask: it would be refused if it asked
    agent.call(StartMeasurement(**IV, dry_run=True))
    profile = agent.call(GetStation())
    for operation in (
        UpdateStation(profile=profile.profile),
        AnswerApproval(id=1, allowed=True),
    ):
        with pytest.raises(LabError) as caught:
            agent.call(operation)
        assert caught.value.code == ErrorCode.DENIED


def test_without_a_window_nobody_can_allow_an_agents_set(lab_as):
    with pytest.raises(LabError) as caught:
        lab_as(AGENT).call(
            SetQuantity(ref="sis_bias_1", key="voltage_set", value=0.001)
        )
    assert caught.value.code == ErrorCode.DENIED and "window" in caught.value.message


def test_a_person_sees_the_change_and_may_allow_another_value(lab_as, window):
    window.lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    thread, done = calling(
        lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
    )
    approval = window.asked()
    assert approval.origin == AGENT and approval.operation == "set_quantity"
    assert "sis_bias_1" in approval.title and approval.text == "1 mV → 2 mV"
    assert approval.value == "2 mV" and not approval.confirm
    window.answer(allowed=True, value="1.5 mV")
    thread.join(5)
    assert done["result"].value == pytest.approx(0.0015)
    wait_for(lambda: bodies(window.heard, ApprovalAnswered))
    (answered,) = bodies(window.heard, ApprovalAnswered)
    assert answered.id == approval.id and answered.answer.by == GUI


def test_a_person_says_no_in_words_the_agent_reads(lab_as, window):
    thread, done = calling(
        lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="voltage_set", value="1V")
    )
    window.lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    window.answer(allowed=False, text="check the pump first")
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    assert "check the pump first" in done["error"].message


def test_a_jump_by_a_factor_is_pointed_out(lab_as, window):
    window.lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    thread, done = calling(
        lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="voltage_set", value="1V")
    )
    assert window.asked().text == "1 mV → 1 V (×1000)"
    window.answer(allowed=False)
    thread.join(5)


def test_a_dangerous_step_is_allowed_only_typing_the_device(lab_as, window):
    thread, done = calling(
        lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="active", value=False)
    )
    approval = window.asked()
    assert approval.confirm == "sis_bias_1" and "damage" in approval.warning
    with pytest.raises(LabError) as caught:
        window.answer(allowed=True)
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    window.answer(allowed=True, confirm="sis_bias_1")
    thread.join(5)
    assert done["result"].value is False


def test_an_agents_start_shows_the_run(lab_as, window):
    thread, done = calling(lab_as(AGENT), StartMeasurement(**IV))
    approval = window.asked()
    assert approval.title.startswith("Start") and "3 points" in approval.text
    assert "bias sis_bias_1" in approval.text
    window.answer(allowed=True)
    thread.join(5)
    assert done["result"].id > 0


def test_a_read_of_a_device_needs_nobody(lab_as):
    agent = lab_as(AGENT)
    agent.call(CallAction(ref="spectrum_analyzer_1", action="read_trace"))


def test_an_agent_asks_and_waits_for_the_answer(lab_as, window):
    agent = lab_as(AGENT)
    pending = agent.call(
        AskUser(question="Cooled down?", options=("yes", "no"), timeout=0.05)
    )
    assert pending.pending and window.asked().options == ("yes", "no")
    with pytest.raises(LabError) as caught:
        window.answer(allowed=True, choice="maybe")
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    window.answer(allowed=True, choice="yes", text="at 4.2 K")
    answered = agent.call(WaitAnswer(id=pending.id, timeout=1))
    assert not answered.pending and answered.answer.choice == "yes"
    assert answered.answer.text == "at 4.2 K"


def test_nobody_answering_withdraws_the_request(lab_as, window, monkeypatch):
    from thzdaq_core.application import approvals

    monkeypatch.setattr(approvals, "ANSWER_S", 0.1)
    with pytest.raises(LabError) as caught:
        lab_as(AGENT).call(SetQuantity(ref="sis_bias_1", key="voltage_set", value=0))
    assert caught.value.code == ErrorCode.DENIED and "nobody" in caught.value.message
    wait_for(lambda: bodies(window.heard, ApprovalAnswered))  # another client's stream
    (answered,) = bodies(window.heard, ApprovalAnswered)
    assert answered.answer.by == approvals.TIMEOUT


def test_a_terminal_that_asks_answers_as_a_window_does(lab_as):
    terminal = Window(lab_as(CLI, ANSWERING_CLI))
    try:
        thread, done = calling(
            lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="voltage_set", value=0)
        )
        terminal.answer(allowed=True)
        thread.join(5)
        assert done["result"].value == 0
    finally:
        terminal.stop()


def test_a_cli_that_does_not_ask_and_an_agents_one_are_nobody(lab_as):
    """A person's CLI that only listens cannot answer; an agent's never can."""
    for origin, kind in ((CLI, CLI), (AGENT_CLI, ANSWERING_CLI)):
        listening = Window(lab_as(origin, kind))
        try:
            with pytest.raises(LabError) as caught:
                lab_as(AGENT).call(
                    SetQuantity(ref="sis_bias_1", key="voltage_set", value=0)
                )
            assert caught.value.code == ErrorCode.DENIED
            assert "approvals watch" in caught.value.message
        finally:
            listening.stop()


def test_an_agents_cli_cannot_answer(lab_as, window):
    thread, done = calling(
        lab_as(AGENT), SetQuantity(ref="sis_bias_1", key="voltage_set", value=0)
    )
    approval = window.asked()
    with pytest.raises(LabError) as caught:
        lab_as(AGENT_CLI).call(AnswerApproval(id=approval.id, allowed=True))
    assert caught.value.code == ErrorCode.DENIED
    window.answer(allowed=False, text="not yet")
    thread.join(5)
    assert "not yet" in done["error"].message
