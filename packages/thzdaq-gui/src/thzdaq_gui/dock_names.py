"""Names of docks, as ADS saves them in the layout, and of measurements
where the window shows them (Ctrl+K, Processes).

A dock of a graph or device is named by its kind and key (graph:I-V,
device:sis_bias_1); the base docks by their kind alone. Saved layouts hold
these names: they never change. A place inside a dock is named the same way:
code:/path/to/pv.py is a file's tab in Editor (where Processes leads to a
script run from it), console:2 a console's tab in Console. A measurement is no
dock: measure:sis.current_vs_voltage names it in the run bar.

Agents name what they point at in a window (thzdaq_api.ui) by these names,
and by two more: a field of a measurement's form,
measure:sis.current_vs_voltage/voltage (a parameter or a slot), and a
control of the run bar, run:start.
"""

from typing import Optional, Tuple

MEASURE = "measure"  # a measurement in the run bar
GRAPH = "graph"
DEVICE = "device"
SETUP = "setup"
DATA = "data"
LOG = "log"
PROCESSES = "processes"
DAEMON = "daemon"
EDITOR = "editor"  # the tabs of scripts' files
CODE = "code"  # a script's file: its tab in Editor
CONSOLE = "console"  # the tabs of Python consoles; console:<number> is one of them
ASSISTANT = "assistant"  # the assistant's chat
RUN = "run"  # a control of the run bar: run:start
FIELD = "/"  # between a measurement and a field of its form

# The controls of the run bar (run:<control>)
LIST = "list"  # the measurements to choose from
PARAMETERS = "parameters"  # the button that drops the form down
GRAPHS = "graphs"
COMMENT = "comment"
START = "start"
CHECK = "check"
STOP = "stop"
ABORT = "abort"


def dock_name(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def kind_of(name: str) -> str:
    """measure:sis.current_vs_voltage -> measure; setup -> setup."""
    return name.split(":", 1)[0]


def key_of(name: str, kind: str) -> Optional[str]:
    """measure:sis.current_vs_voltage, measure -> sis.current_vs_voltage; None for another kind."""
    prefix = kind + ":"
    return name[len(prefix) :] if name.startswith(prefix) else None


def field_name(procedure: str, field: str) -> str:
    """sis.current_vs_voltage, voltage -> measure:sis.current_vs_voltage/voltage."""
    return f"{dock_name(MEASURE, procedure)}{FIELD}{field}"


def measure_parts(name: str) -> Tuple[Optional[str], Optional[str]]:
    """measure:sis.current_vs_voltage/voltage -> (sis.current_vs_voltage, voltage);
    the field None for a measurement itself; (None, None) for another kind."""
    key = key_of(name, MEASURE)
    if key is None:
        return None, None
    procedure, separator, field = key.partition(FIELD)
    return procedure, field if separator else None
