from typing import Literal, Optional

from thzdaq_instruments.instrument import Instrument

LoadPosition = Literal["hot", "cold"]


class SimChopper(Instrument):
    def __init__(self, *, name: Optional[str] = None, position: LoadPosition = "cold"):
        super().__init__(name=name)
        self.position: LoadPosition = position
        self.moves = 0

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
