"""What agents ask of a window (offscreen): its state, a place shown, the
form of a measurement filled, a highlight over a field of the run bar or a
dock that goes when the person acts (WindowGuide, OverlayGuide). An agent
calls from a thread of its own, as it does through the daemon."""

import os
from pathlib import Path

import pytest
from lab_helpers import calling
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.procedures import (
    CURRENT_VS_VOLTAGE,
    POWER_VS_VOLTAGE,
    TWO_SB_SIDEBAND_RATIO,
)
from thzdaq_api.ui import (
    BEHIND,
    CLOSED,
    FRONT,
    UiFillMeasurement,
    UiHighlight,
    UiOpen,
    UiState,
)
from thzdaq_gui.dock_names import LOG, RUN, START, dock_name, field_name
from thzdaq_gui.overlay import OverlayGuide

# Pictures of the highlights for a person to look at, when asked for (a folder)
SHOTS = os.environ.get("THZDAQ_SHOTS")
VOLTAGE = field_name(CURRENT_VS_VOLTAGE, "voltage")


@pytest.fixture
def agent(session):
    return session.lab_of(True, "mcp:claude-code", "mcp")


@pytest.fixture
def ask(agent, wait):
    """An agent's call, answered by the window in the GUI thread."""

    def asking(operation):
        thread, done = calling(agent, operation)
        wait(lambda: not thread.is_alive())
        if "error" in done:
            raise done["error"]
        return done["result"]

    return asking


def refused(ask, operation) -> LabError:
    with pytest.raises(LabError) as caught:
        ask(operation)
    return caught.value


def overlay(window):
    return window.guide.overlay


def shot(widget, name: str) -> None:
    if SHOTS:
        widget.grab().save(str(Path(SHOTS) / f"{name}.png"))


def test_the_window_tells_its_docks_controls_and_chosen_form(window, ask):
    window.runBar.choose(CURRENT_VS_VOLTAGE)
    state = ask(UiState())
    assert state.window == window.session.window
    assert state.windows == (window.session.window,)
    docks = {d.name: d for d in state.docks}
    assert docks[LOG].state in (BEHIND, CLOSED, FRONT) and docks[LOG].title == "Log"
    controls = {c.name: c for c in state.controls}
    assert controls[dock_name(RUN, START)].enabled
    assert dock_name(RUN, "abort") not in controls  # not shown while nothing hangs
    form = state.measurement
    assert (form.procedure, form.open) == (CURRENT_VS_VOLTAGE, False)
    fields = {f.name: f for f in form.fields}
    assert fields[VOLTAGE].unit == "mV" and fields[VOLTAGE].value == "0:7:351"
    bias = fields[field_name(CURRENT_VS_VOLTAGE, "bias")]
    assert bias.kind == "device" and bias.value in bias.choices


def test_a_form_is_filled_and_shown_but_not_started(window, ask):
    form = ask(
        UiFillMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            typed={"voltage": "-2:5:71"},
            devices={"bias": "sis_bias_2"},
        )
    )
    fields = {f.key: f.value for f in form.fields}
    assert (fields["voltage"], fields["bias"]) == ("-2:5:71", "sis_bias_2")
    assert form.open and window.runBar.parameters.isVisible()
    box = window.measures.form(CURRENT_VS_VOLTAGE).box
    assert box.parameters()["voltage"] == {"start": -0.002, "stop": 0.005, "points": 71}
    assert not box.runner.running and window.session.running() == []
    error = refused(
        ask,
        UiFillMeasurement(procedure=CURRENT_VS_VOLTAGE, devices={"bias": "nothing"}),
    )
    assert error.code == ErrorCode.INVALID_ARGUMENTS and "sis_bias_1" in error.hint


def test_a_dock_folded_into_its_side_bar_is_opened(window, ask):
    window.docks[LOG].autoHideDockContainer().collapseView(True)
    assert window.docks.state(LOG) == BEHIND
    ask(UiOpen(place=LOG))
    assert window.docks.state(LOG) == FRONT
    error = refused(ask, UiOpen(place="device:nothing"))
    assert error.code == ErrorCode.NOT_FOUND


def test_a_highlight_over_a_field_follows_it_and_goes_on_escape(window, ask, wait):
    window.runBar.choose(POWER_VS_VOLTAGE)  # another measurement chosen first
    window.runBar.parameters.hide()
    ask(UiHighlight(anchor=VOLTAGE, text="Sweep from -2 to 5 mV here"))
    bar = window.runBar
    assert bar.chosen == CURRENT_VS_VOLTAGE and bar.parameters.isVisible()
    shown = overlay(window)
    box = window.measures.form(CURRENT_VS_VOLTAGE).box
    anchor = box.form.widget("voltage")
    assert shown.anchor is anchor and shown.parentWidget() is bar.parameters
    assert box.parameters_box.expanded()
    corner = anchor.mapTo(bar.parameters, QPoint(0, 0))
    assert shown.frame().contains(corner)
    shot(bar.parameters, "highlight_field")
    bar.parameters.resize(bar.parameters.width() + 40, bar.parameters.height())
    wait(lambda: shown.geometry() == bar.parameters.rect())
    QApplication.sendEvent(
        anchor, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    )
    assert overlay(window) is None and not shown.isVisible()


def test_a_highlight_over_a_dock_goes_on_a_click(window, ask):
    ask(UiHighlight(anchor=LOG, text="What the measurement told is here"))
    shown = overlay(window)
    assert shown.anchor is window.docks[LOG] and shown.parentWidget() is window
    shot(window, "highlight_dock")
    QTest.mouseClick(window.runBar.controls.comment, Qt.LeftButton)
    assert overlay(window) is None


def test_a_new_highlight_takes_the_place_of_the_last(window, ask):
    ask(UiHighlight(anchor=dock_name(RUN, START), text="Then press Start"))
    first = overlay(window)
    assert first.anchor is window.runBar.controls.btnStart
    ask(UiHighlight(anchor=LOG))
    assert overlay(window) is not first and first.ended  # deleted by now


def test_a_place_that_cannot_be_highlighted_is_refused_with_why(window, ask):
    error = refused(ask, UiHighlight(anchor="nowhere"))
    assert error.code == ErrorCode.NOT_FOUND and "ui_state" in error.hint
    error = refused(ask, UiHighlight(anchor=field_name(CURRENT_VS_VOLTAGE, "nothing")))
    assert error.code == ErrorCode.NOT_FOUND
    # Used only with a spectrum analyzer; a power meter is the default
    unused = field_name(TWO_SB_SIDEBAND_RATIO, "resolution_bandwidth")
    error = refused(ask, UiHighlight(anchor=unused))
    assert error.code == ErrorCode.NOT_ALLOWED and "used when" in error.hint
    assert overlay(window) is None


def test_the_window_the_person_comes_to_is_asked(window, session, ask):
    other = session.lab_of(True, "gui", "gui", "another")
    stop = other.subscribe(lambda event: None)  # a window that never answers
    try:
        own = window.session.window
        # Before the person comes to a window, the last to open is asked first
        assert ask(UiState(window=own)).windows == ("another", own)
        QApplication.sendEvent(window, QEvent(QEvent.WindowActivate))
        assert ask(UiState()).window == window.session.window
    finally:
        stop()


def test_an_overlay_goes_with_its_anchor(window):
    shown = OverlayGuide(window.runBar.controls.btnCheck, "here")
    window.runBar.controls.btnCheck.hide()
    assert shown.ended
