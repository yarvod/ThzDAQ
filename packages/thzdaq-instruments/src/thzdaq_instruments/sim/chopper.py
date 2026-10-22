from typing import Literal, Optional

from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.quantities import CHOPPER_QUANTITIES

LoadPosition = Literal["hot", "cold"]


class SimChopper(Instrument):
    """Chopper with the controls of the Modbus one: moves, alignment, rotation."""

    quantities = CHOPPER_QUANTITIES

    def __init__(self, *, name: Optional[str] = None, position: LoadPosition = "cold"):
        super().__init__(name=name)
        self.position: LoadPosition = position
        self.moves = 0
        self.frequency = 10.0
        self.running = False

    def identify(self) -> str:
        return "THZDAQ,SimChopper,0,1.0"

    def _move(self, position: LoadPosition) -> None:
        if self.position != position:
            self.moves += 1
        self.position = position

    def to_hot(self) -> None:
        self._move("hot")

    def to_cold(self) -> None:
        self._move("cold")

    def load_state(self) -> str:
        return "between" if self.running else self.position

    def rotate(self, angle: float = 90, slow: bool = False, align: bool = True) -> None:
        if round(angle / 90) % 2:
            self._move("cold" if self.position == "hot" else "hot")

    def align(self) -> None:
        pass

    def set_frequency(self, frequency: float) -> None:
        self.frequency = frequency

    def start_rotation(
        self, frequency: Optional[float] = None, acc_time: int = 0
    ) -> None:
        if frequency is not None:
            self.frequency = frequency
        self.running = True

    def stop(self, stop_time: int = 0, timeout: Optional[float] = None) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running
