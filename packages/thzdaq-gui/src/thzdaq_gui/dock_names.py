"""Names of docks, as ADS saves them in the layout, and of measurements
where the window shows them (Ctrl+K, Processes).

A dock of a graph or device is named by its kind and key (graph:I-V,
device:sis_bias_1); the base docks by their kind alone. Saved layouts hold
these names: they never change. A place inside a dock is named the same way:
code:/path/to/pv.py is a file's tab in Editor (where Processes leads to a
script run from it), console:2 a console's tab in Console. A measurement is no
dock: measure:sis.current_vs_voltage names it in the run bar.
"""

from typing import Optional

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


def dock_name(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def kind_of(name: str) -> str:
    """measure:sis.current_vs_voltage -> measure; setup -> setup."""
    return name.split(":", 1)[0]


def key_of(name: str, kind: str) -> Optional[str]:
    """measure:sis.current_vs_voltage, measure -> sis.current_vs_voltage; None for another kind."""
    prefix = kind + ":"
    return name[len(prefix) :] if name.startswith(prefix) else None
