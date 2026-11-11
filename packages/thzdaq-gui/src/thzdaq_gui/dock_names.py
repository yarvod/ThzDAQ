"""Names of docks, as ADS saves them in the layout.

A dock of a measurement, graph, device or script's file is named by its kind
and key (measure:sis.current_vs_voltage, graph:I-V, device:sis_bias_1,
code:/path/to/pv.py); the base docks by their kind alone. Saved layouts hold
these names: they never change.
"""

from typing import Optional

MEASURE = "measure"
GRAPH = "graph"
DEVICE = "device"
SETUP = "setup"
DATA = "data"
LOG = "log"
PROCESSES = "processes"
DAEMON = "daemon"
CODE = "code"  # the dock of a script's file


def dock_name(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def kind_of(name: str) -> str:
    """measure:sis.current_vs_voltage -> measure; setup -> setup."""
    return name.split(":", 1)[0]


def key_of(name: str, kind: str) -> Optional[str]:
    """measure:sis.current_vs_voltage, measure -> sis.current_vs_voltage; None for another kind."""
    prefix = kind + ":"
    return name[len(prefix) :] if name.startswith(prefix) else None
