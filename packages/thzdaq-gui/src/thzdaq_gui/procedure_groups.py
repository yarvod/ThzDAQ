"""Groups of procedures (the part of a name before the dot) as the GUI shows them:
their order in the run bar and menus, title and icon, in one place."""

from dataclasses import dataclass

from thzdaq_api.procedures import GRID, IF, MONITOR, SIS, TWO_SB, group_of


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    icon: str  # qtawesome name


GROUPS = (
    Group(SIS, "SIS", "alpha-s-box-outline"),
    Group(IF, "IF", "waveform"),
    Group(TWO_SB, "2SB", "chart-bell-curve-cumulative"),
    Group(MONITOR, "Monitor", "monitor-eye"),
    Group(GRID, "Grid", "rotate-3d-variant"),
)
_BY_KEY = {group.key: group for group in GROUPS}


def group(procedure: str) -> Group:
    """The group of a procedure; a group not listed here shows its key, last."""
    key = group_of(procedure)
    return _BY_KEY.get(key) or Group(key, key, "play-circle-outline")


def rank(procedure: str) -> int:
    """Where the procedure's group stands in GROUPS; groups not listed come last."""
    return next(
        (i for i, g in enumerate(GROUPS) if g.key == group_of(procedure)), len(GROUPS)
    )
