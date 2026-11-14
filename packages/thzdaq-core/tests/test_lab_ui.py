"""What agents ask of a person's window (thzdaq_api.ui) goes to one window:
the one named, else the one the person was at last; the window answers
through the daemon (contract: LocalLab and RemoteLab)."""

import pytest
from lab_helpers import Screen, bodies, wait_for
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ApprovalRequested
from thzdaq_api.origins import ASSISTANT, ASSISTANT_CLIENT, GUI, script
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.tools import Reach, by_name, tools
from thzdaq_api.ui import (
    DEVICE,
    PARAMETER,
    AnswerUi,
    FieldState,
    FormState,
    UiFillMeasurement,
    UiHighlight,
    UiOpen,
    UiState,
    WindowActive,
    WindowState,
)
from thzdaq_core.application import windows


@pytest.fixture
def agent(lab_as):
    return lab_as("mcp:claude-code")


def windows_of(status):
    return [c.window for c in status.clients if c.window]


@pytest.fixture
def screens(lab_as):
    """Main windows of a person, each answering ui_state with its id, and
    what else it is asked with shown(operation)."""
    opened = []

    def screen(window, shown=lambda operation: None):
        def answer(operation):
            if isinstance(operation, UiState):
                return WindowState(window, window, (), ())
            return shown(operation)

        lab = lab_as(GUI, window=window)
        found = Screen(lab, answer)
        wait_for(lambda: window in windows_of(lab.call(GetDaemonStatus())))
        opened.append(found)
        return found

    yield screen
    for found in opened:
        found.stop()


def refused(lab, operation) -> LabError:
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    return caught.value


def test_with_no_window_open_an_agent_is_told_to_open_one(agent):
    error = refused(agent, UiState())
    assert error.code == ErrorCode.NOT_FOUND
    assert error.message == windows.NO_WINDOW and "thzdaq gui" in error.hint


def test_a_call_goes_to_the_window_named_else_the_one_the_person_was_at(agent, screens):
    first, second = screens("1-1"), screens("2-1")
    assert agent.call(UiState()).window == "2-1"  # none was active: the last one
    first.lab.call(WindowActive(window="1-1"))
    state = agent.call(UiState())
    assert state.window == "1-1"
    assert state.windows == ("1-1", "2-1")  # the one the person was at first
    assert agent.call(UiState(window="2-1")).window == "2-1"
    second.lab.call(WindowActive(window="2-1"))
    assert agent.call(UiState()).window == "2-1"
    assert len(first.asked) == 1 and len(second.asked) == 3


def test_a_window_that_closed_is_asked_no_more(agent, screens):
    first, second = screens("1-1"), screens("2-1")
    second.lab.call(WindowActive(window="2-1"))
    second.stop()
    # A stream the daemon serves ends at its next heartbeat that finds it gone
    wait_for(lambda: "2-1" not in windows_of(agent.call(GetDaemonStatus())), 10)
    assert agent.call(UiState()).window == "1-1"
    error = refused(agent, UiState(window="2-1"))
    assert error.code == ErrorCode.NOT_FOUND and "1-1" in error.hint


def test_the_window_gets_the_operation_and_its_refusal_reaches_the_agent(
    agent, screens
):
    def shown(operation):
        if isinstance(operation, UiHighlight) and operation.anchor == "nowhere":
            raise LabError(
                ErrorCode.NOT_FOUND, "No place nowhere", "ui_state names them"
            )

    screen = screens("1-1", shown)
    agent.call(UiOpen(place="log"))
    agent.call(UiHighlight(anchor="run:start", text="Press Start"))
    error = refused(agent, UiHighlight(anchor="nowhere"))
    assert (error.code, error.message) == (ErrorCode.NOT_FOUND, "No place nowhere")
    assert screen.asked[:2] == [
        UiOpen(place="log", window="1-1"),
        UiHighlight(anchor="run:start", text="Press Start", window="1-1"),
    ]


def test_a_form_is_filled_with_values_checked_and_in_si(agent, screens):
    def shown(operation):
        return FormState(operation.procedure, "SIS I-V", True, ())

    screen = screens("1-1", shown)
    form = agent.call(
        UiFillMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            typed={"voltage": "-2:5:71"},
            parameters={"settle_time": 0.02},
            devices={"bias": "sis_bias_2"},
        )
    )
    assert form.procedure == CURRENT_VS_VOLTAGE
    (asked,) = screen.asked
    assert asked.parameters == {
        "voltage": {"start": -0.002, "stop": 0.005, "points": 71},
        "settle_time": 0.02,
    }
    assert (asked.typed, asked.devices) == ({}, {"bias": "sis_bias_2"})
    error = refused(
        agent, UiFillMeasurement(procedure=CURRENT_VS_VOLTAGE, typed={"voltage": "x"})
    )
    assert error.code == ErrorCode.INVALID_ARGUMENTS
    assert len(screen.asked) == 1  # a value that is wrong never reaches the window


def test_a_window_that_does_not_answer_lets_the_agent_go(agent, lab_as, monkeypatch):
    monkeypatch.setattr(windows, "UI_S", 0.2)
    silent = lab_as(GUI, window="1-1")
    stop = silent.subscribe(lambda event: None)
    try:
        error = refused(agent, UiState())
    finally:
        stop()
    assert error.code == ErrorCode.NOT_FOUND and "did not answer" in error.message


def test_agents_and_the_assistant_look_and_point_without_asking(lab_as, screens):
    screen = screens("1-1")
    heard = []
    stop = screen.lab.subscribe(heard.append)
    try:
        for asking in (lab_as("mcp:codex"), lab_as(ASSISTANT, ASSISTANT_CLIENT)):
            asking.call(UiState())
            asking.call(UiHighlight(anchor="log"))
    finally:
        stop()
    assert not bodies(heard, ApprovalRequested)
    assert len(screen.asked) == 4


def test_only_a_window_answers_for_a_window(lab_as):
    for origin in ("mcp:claude-code", ASSISTANT, script("sweep")):
        error = refused(lab_as(origin), AnswerUi(id=1, result=None))
        assert error.code == ErrorCode.DENIED
    error = refused(lab_as(GUI), AnswerUi(id=1, result=None))
    assert error.code == ErrorCode.NOT_FOUND  # allowed, but nothing waits as 1


def test_the_assistants_tools_show_in_its_own_window(lab_as, screens):
    other = screens("1-1")
    own = screens("2-1")
    other.lab.call(WindowActive(window="1-1"))
    reach = Reach(lab_as(ASSISTANT, ASSISTANT_CLIENT))
    try:
        found = by_name(tools(lambda: None, lambda: "2-1"))
        assert "window" not in found["ui_highlight"].schema()["properties"]
        tool = found["ui_state"]
        assert tool.call(reach, tool.arguments({"window": "1-1"}), None).startswith(
            "window 2-1"
        )
        tool = found["ui_highlight"]
        args = tool.arguments({"anchor": "run:start", "text": "Press Start"})
        assert tool.call(reach, args, None).startswith("run:start is highlighted")
        assert own.asked[-1] == UiHighlight(
            anchor="run:start", text="Press Start", window="2-1"
        )
    finally:
        reach.close()


def test_an_agents_tools_show_in_the_window_the_person_was_at(lab_as, screens):
    def shown(operation):
        return FormState(
            operation.procedure,
            "SIS I-V",
            True,
            (
                FieldState(
                    f"measure:{CURRENT_VS_VOLTAGE}/bias", "bias", DEVICE, "SIS bias",
                    "sis_bias_2", choices=("sis_bias_1", "sis_bias_2"),
                ),  # fmt: skip
                FieldState(
                    f"measure:{CURRENT_VS_VOLTAGE}/voltage", "voltage", PARAMETER,
                    "Voltage", "-2:5:71", "mV",
                ),  # fmt: skip
            ),
            folded=("devices",),
        )

    screens("1-1")
    screens("2-1", shown).lab.call(WindowActive(window="2-1"))
    reach = Reach(lab_as("mcp:codex"))
    try:
        found = by_name(tools(lambda: None))
        assert "window" in found["ui_state"].schema()["properties"]
        tool = found["ui_fill_measurement"]
        args = tool.arguments(
            {"procedure": CURRENT_VS_VOLTAGE, "typed": {"voltage": "-2:5:71"}}
        )
        assert tool.call(reach, args, None).splitlines() == [
            f"measurement {CURRENT_VS_VOLTAGE}: SIS I-V (form open, devices folded)",
            f"  measure:{CURRENT_VS_VOLTAGE}/bias (device SIS bias): sis_bias_2 "
            "[sis_bias_1, sis_bias_2]",
            f"  measure:{CURRENT_VS_VOLTAGE}/voltage (parameter Voltage): -2:5:71 mV",
        ]
        tool = found["ui_state"]
        text = tool.call(reach, tool.arguments({}), None)
        assert text.startswith("window 2-1: 2-1 (other windows: 1-1)")
    finally:
        reach.close()
