from typing import Optional

from thzdaq_instruments.angle import CountedAngle
from thzdaq_instruments.sim.base import SimInstrument


class SimRotator(CountedAngle, SimInstrument):
    """The wire grid as the bench has it: it moves by differences and counts
    its angle (thzdaq_instruments.angle); position is where it really is."""

    driver_key = "sim.rotator"
    device_type = "grid"

    def __init__(self, *, name: Optional[str] = None, angle: float = 0.0):
        super().__init__(name=name)
        self._angle = angle
        self.position = angle

    def identify(self) -> str:
        return "THZDAQ,SimRotator,0,1.0"

    def _move(self, angle: float) -> None:
        self.position += angle - self.get_angle()
