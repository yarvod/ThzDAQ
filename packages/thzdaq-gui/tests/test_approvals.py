"""An agent asks the person at the window: a modal dialog to allow, change or
refuse what it wants, or to answer its question."""

import threading

import pytest
from thzdaq_api.approvals import AnswerApproval, AskUser, WaitAnswer
from thzdaq_api.devices import SetQuantity
from thzdaq_api.errors import ErrorCode, LabError

AGENT = "mcp:claude"


@pytest.fixture
def agent(session):
    lab = session.lab_of(True)
    lab.origin = AGENT
    return lab


def calling(lab, operation):
    done = {}

    def call():
        try:
            done["result"] = lab.call(operation)
        except LabError as e:
            done["error"] = e

    thread = threading.Thread(target=call)
    thread.start()
    return thread, done


def dialog_of(window, wait):
    wait(lambda: window.approvalPrompts.current is not None)
    return window.approvalPrompts.current


def test_the_person_changes_the_value_and_allows_it(window, session, agent, wait):
    session.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    thread, done = calling(
        agent, SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
    )
    dialog = dialog_of(window, wait)
    assert dialog.isVisible() and dialog.isModal()
    assert dialog.approval.text == "1 mV → 2 mV" and dialog.value.text() == "2 mV"
    dialog.value.setText("1.5 mV")
    dialog.allow.click()
    wait(lambda: "result" in done)
    thread.join(5)
    assert done["result"].value == pytest.approx(0.0015)
    wait(lambda: window.approvalPrompts.current is None)


def test_the_person_refuses_with_words_for_the_agent(window, agent, wait):
    thread, done = calling(
        agent, SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
    )
    dialog = dialog_of(window, wait)
    dialog.words.setText("check the pump first")
    dialog.deny.click()
    wait(lambda: "error" in done)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    assert "check the pump first" in done["error"].message


def test_an_answer_from_another_window_closes_the_dialog(window, session, agent, wait):
    thread, done = calling(
        agent, SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
    )
    dialog = dialog_of(window, wait)
    other = session.lab_of(True)  # another window of the same person
    other.call(AnswerApproval(id=dialog.approval.id, allowed=False))
    wait(lambda: window.approvalPrompts.current is None)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED


def test_a_dangerous_step_is_allowed_once_its_device_is_typed(window, agent, wait):
    thread, done = calling(
        agent, SetQuantity(ref="sis_bias_1", key="active", value=False)
    )
    dialog = dialog_of(window, wait)
    assert not dialog.allow.isEnabled()
    dialog.confirm.setText("sis_bias_1")
    assert dialog.allow.isEnabled()
    dialog.allow.click()
    wait(lambda: "result" in done)
    thread.join(5)
    assert done["result"].value is False


def test_a_question_is_answered_with_a_choice_and_words(window, agent, wait):
    asked = agent.call(
        AskUser(question="Is the LO locked?", options=("yes", "no"), timeout=0.05)
    )
    dialog = dialog_of(window, wait)
    assert dialog.allow.text() == "Answer" and dialog.value is None
    dialog.choice.setCurrentText("no")
    dialog.words.setText("relock at 11.2 GHz")
    dialog.allow.click()
    answer = agent.call(WaitAnswer(id=asked.id, timeout=5)).answer
    assert answer.choice == "no" and answer.text == "relock at 11.2 GHz"


def test_closing_the_dialog_refuses(window, agent, wait):
    thread, done = calling(
        agent, SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
    )
    dialog_of(window, wait).reject()  # Escape, or the close button
    wait(lambda: "error" in done)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
