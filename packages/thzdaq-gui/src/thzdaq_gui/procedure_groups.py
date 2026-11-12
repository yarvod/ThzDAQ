"""Groups of procedures (the part of a name before the dot) as the GUI shows them:
their order in the run bar and menus, title and icon, in one place. A
measurement's icon is an M in a square; the monitor keeps its own."""

from dataclasses import dataclass

from thzdaq_api.custom import GROUP as CUSTOM
from thzdaq_api.procedures import IF, MONITOR, SIS, TWO_SB, group_of


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    icon: str  # qtawesome name


MEASUREMENT = "alpha-m-box-outline"

GROUPS = (
    Group(SIS, "SIS", MEASUREMENT),
    Group(IF, "IF", MEASUREMENT),
    Group(TWO_SB, "2SB", MEASUREMENT),
    Group(MONITOR, "Monitor", "monitor-eye"),
    Group(CUSTOM, "Custom", MEASUREMENT),  # the bench's own measurements
)
_BY_KEY = {group.key: group for group in GROUPS}


def group(procedure: str) -> Group:
    """The group of a procedure; a group not listed here shows its key, last."""
    key = group_of(procedure)
    return _BY_KEY.get(key) or Group(key, key, MEASUREMENT)


def rank(procedure: str) -> int:
    """Where the procedure's group stands in GROUPS; groups not listed come last."""
    return next(
        (i for i, g in enumerate(GROUPS) if g.key == group_of(procedure)), len(GROUPS)
    )
