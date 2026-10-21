from typing import Optional

from thzdaq_instruments.instrument import Instrument


class SimYigFilter(Instrument):
    """YIG filter tuned by a DAC code: frequency = start + code * step."""

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        start_frequency: float = 2.97320263e9,  # Hz at code 0
        step: float = 2.46705639e6,  # Hz per code
        max_code: int = 4095,
    ):
        super().__init__(name=name)
        self.start_frequency = start_frequency
        self.step = step
        self.max_code = max_code
        self.frequency = start_frequency

    def identify(self) -> str:
        return "THZDAQ,SimYigFilter,0,1.0"

    def tune(self, frequency: float) -> float:
        code = round((frequency - self.start_frequency) / self.step)
        code = min(max(code, 0), self.max_code)
        self.frequency = self.start_frequency + code * self.step
        return self.frequency
