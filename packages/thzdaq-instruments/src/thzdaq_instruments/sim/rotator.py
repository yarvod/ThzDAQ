from typing import Optional

from thzdaq_instruments.instrument import Instrument


class SimRotator(Instrument):
    def __init__(self, *, name: Optional[str] = None, angle: float = 0.0):
        super().__init__(name=name)
        self.angle = angle

    def identify(self) -> str:
        return "THZDAQ,SimRotator,0,1.0"

    def rotate_to(self, angle: float) -> float:
        self.angle = angle
        return angle

    def get_angle(self) -> float:
        return self.angle
