"""Names of docks, as ADS saves them in layouts and perspectives.

A dock of a measurement, graph or device is named by its kind and key
(measure:sis.iv_curve, graph:I-V, device:sis_bias_1); the base docks and the
Lite Measurement dock by their kind alone. Saved layouts hold these names:
they never change.
"""

from typing import Optional

MEASURE = "measure"
GRAPH = "graph"
DEVICE = "device"
MEASUREMENT = "measurement"  # Lite: the chosen measurement
SETUP = "setup"
DATA = "data"
LOG = "log"
PROCESSES = "processes"


def dock_name(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def kind_of(name: str) -> str:
    """measure:sis.iv_curve -> measure; setup -> setup."""
    return name.split(":", 1)[0]


def key_of(name: str, kind: str) -> Optional[str]:
    """measure:sis.iv_curve, measure -> sis.iv_curve; None for another kind."""
    prefix = kind + ":"
    return name[len(prefix) :] if name.startswith(prefix) else None
