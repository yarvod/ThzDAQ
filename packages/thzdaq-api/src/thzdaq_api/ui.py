"""The ThzDAQ window as agents see it and point into it, for the person at it.

An agent reads a window's structure (ui_state: names and values, no pixels),
shows a dock or a measurement (ui_open), fills the form of a measurement in
the bar on top (ui_fill_measurement: it starts nothing, the person presses
Start) and highlights a place with a short text (ui_highlight). Each goes to
one window: the one named by window, else the one a person was at last. The
assistant of a window always goes to its own.

The daemon asks the window with an event (ui_requested) and the window
answers with answer_ui: what a window shows lives in the window, and is
asked when it is needed.
"""

import itertools
import os
from typing import Any, Dict, Optional, Tuple

import msgspec

from thzdaq_api.errors import Failure
from thzdaq_api.operation import Operation, Rights

# How long an agent's call waits for its window to answer
UI_S = 10.0

# Docks and fields as a window tells them
FRONT, BEHIND, CLOSED = "front", "behind", "closed"
DEVICE, PARAMETER = "device", "parameter"  # the kinds of a form's fields

_numbers = itertools.count(1)


def window_id() -> str:
    """A main window's id, <pid>-<n>: it stays while the window lives, through
    reconnections and restarts of the daemon."""
    return f"{os.getpid()}-{next(_numbers)}"


class DockState(msgspec.Struct, frozen=True):
    """A dock of a window: in front, behind another one (or folded into a side
    bar), or closed."""

    name: str  # the anchor that names it: log, device:sis_bias_1, graph:I-V
    title: str
    state: str


class ControlState(msgspec.Struct, frozen=True):
    """A control of the bar on top: run:start, run:stop, ..."""

    name: str
    title: str
    enabled: bool = True


class FieldState(msgspec.Struct, frozen=True):
    """A field of a measurement's form: a device chosen for a slot, or a
    parameter as it is typed (in its unit: a sweep start:stop:points)."""

    name: str  # its anchor: measure:<procedure>/<slot or parameter>
    key: str  # the slot or the parameter
    kind: str  # device or parameter
    label: str
    value: str
    unit: str = ""
    choices: Tuple[str, ...] = ()  # the devices that suit a slot, a choice's options
    used: bool = True  # the run uses it with these values (shown_if)


class FormState(msgspec.Struct, frozen=True):
    """The measurement chosen in the bar on top and its form."""

    procedure: str
    title: str
    open: bool  # the form drops down under the settings button now
    fields: Tuple[FieldState, ...]
    folded: Tuple[str, ...] = ()  # its sections folded: devices, parameters
    running: bool = False


class WindowState(msgspec.Struct, frozen=True):
    """A window as an agent sees it: names to open and highlight, values."""

    window: str  # its id
    title: str
    docks: Tuple[DockState, ...]
    controls: Tuple[ControlState, ...]
    measurement: Optional[FormState] = None
    running: Tuple[str, ...] = ()  # procedures the window's measurements run
    windows: Tuple[str, ...] = ()  # every window open, the one a person was at first


class UiState(Operation[WindowState]):
    """What a ThzDAQ window shows: its docks (front, behind, closed), the
    controls of the bar on top, the measurement chosen there with its form
    (devices by slot, parameters as typed, in their units) and the windows
    open. Names in it are what ui_open and ui_highlight take. window: one of
    the windows open; none: the one the person was at last."""

    window: Optional[str] = None


class UiOpen(Operation[None]):
    """Show the person a dock or a measurement of a ThzDAQ window, by its name
    as ui_state lists it: a dock comes to the front, a measurement is chosen
    in the bar on top and its form opens."""

    place: str
    window: Optional[str] = None


class UiFillMeasurement(Operation[FormState]):
    """Choose a measurement in the bar on top of a ThzDAQ window and fill its
    form for the person, who checks it and presses Start: it starts nothing.
    Values as start_measurement takes them (typed: in the units they are
    shown in, a sweep start:stop:points); fields not given stay. Returns the
    form as the window shows it now."""

    procedure: str
    parameters: Dict[str, Any] = {}
    typed: Dict[str, str] = {}
    devices: Dict[str, str] = {}  # slot -> device
    window: Optional[str] = None


class UiHighlight(Operation[None]):
    """Point the person at a place of a ThzDAQ window: a dock, a measurement,
    a field of its form or a control of the bar on top, by its name as
    ui_state lists it, with a short text next to it. The place is opened
    first; the highlight goes when the person acts there."""

    anchor: str
    text: str = ""
    window: Optional[str] = None


class WindowActive(Operation[None]):
    """A window tells that the person is at it now: agents' calls without a
    window go to it."""

    window: str


class AnswerUi(Operation[None]):
    """A window answers what was asked of it (ui_requested): the result as
    JSON, or why it could not."""

    rights = Rights.ANSWER
    id: int
    result: Any = None
    failure: Optional[Failure] = None
