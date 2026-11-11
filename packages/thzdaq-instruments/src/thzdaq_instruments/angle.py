"""A rotator that knows its angle only by counting its moves (no position
readback): the wire grid (ArduinoGrid) and its simulator.

The count is its kept state (thzdaq_instruments.state): before a move it tells
where it goes, after it that it stands there. A move that did not end (the
program stopped, the link broke) leaves the angle unknown: it is not read, and
a grid that moves by differences does not move, until zero() makes where it
stands 0°. A move the rotator refused (it answered so) leaves it where it was.
"""

from typing import Any, Mapping, Optional

from thzdaq_instruments.actions import ZERO_ANGLE
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.state import KeepsState, State

ANGLE = "angle"  # where it stands, deg; None: unknown
MOVING_TO = "moving_to"  # where a move that has not ended goes


class AngleUnknown(InstrumentResponseError):
    """The rotator's angle is not known: a move did not end."""


class CountedAngle(KeepsState):
    """Rotator (rotate_to, get_angle) and KeptState of an instrument class;
    the class moves the rotator in _move()."""

    actions = (ZERO_ANGLE,)
    name: str
    _angle: Optional[float] = 0.0

    @property
    def unknown(self) -> str:
        """Why the angle cannot be read, and what helps."""
        return "angle unknown, a move did not end: set its zero where it stands"

    def get_angle(self) -> float:
        """deg; AngleUnknown when a move did not end."""
        if self._angle is None:
            raise AngleUnknown(f"{self.name}: {self.unknown}")
        return self._angle

    def zero(self) -> None:
        """Where it stands is 0° from now on; nothing moves."""
        self.set_angle_reference(0.0)

    def set_angle_reference(self, angle: float) -> None:
        """Tell where it stands without moving it."""
        self._angle = float(angle)
        self.keep()

    def rotate_to(self, angle: float) -> float:
        angle = float(angle)
        self.keep({**self.kept_state(), MOVING_TO: angle})
        try:
            self._move(angle)
        except InstrumentResponseError:
            self.keep()  # it answered: it has not moved
            raise
        except BaseException:
            self._angle = None  # it may have moved part of the way
            self.keep()
            raise
        self._angle = angle
        self.keep()
        return angle

    def _move(self, angle: float) -> None:
        """Rotate to angle from where it stands (get_angle(), when it moves by
        differences); InstrumentResponseError when it refused and did not move."""
        raise NotImplementedError

    def kept_state(self) -> State:
        return {ANGLE: self._angle}

    def restore_state(self, state: Mapping[str, Any]) -> None:
        stands = state.get(ANGLE)
        moved = MOVING_TO in state or stands is None
        self._angle = None if moved else float(stands)
