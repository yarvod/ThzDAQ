from typing import Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument


class SimSignalGenerator(Instrument):
    def __init__(
        self,
        *,
        name: Optional[str] = None,
        min_frequency: float = 250e3,
        max_frequency: float = 40e9,
        min_power: float = -135.0,
        max_power: float = 25.0,
    ):
        super().__init__(name=name)
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.min_power = min_power
        self.max_power = max_power
        self._frequency = min_frequency
        self._power = min_power
        self._output = False

    def identify(self) -> str:
        return "THZDAQ,SimSignalGenerator,0,1.0"

    def set_frequency(self, frequency: float) -> None:
        if not self.min_frequency <= frequency <= self.max_frequency:
            raise InstrumentResponseError(
                f"{self.name}: frequency {frequency} Hz out of range"
            )
        self._frequency = frequency

    def get_frequency(self) -> float:
        return self._frequency

    def set_power(self, power: float) -> None:
        if not self.min_power <= power <= self.max_power:
            raise InstrumentResponseError(
                f"{self.name}: power {power} dBm out of range"
            )
        self._power = power

    def get_power(self) -> float:
        return self._power

    def set_output(self, value: bool) -> None:
        self._output = bool(value)

    def get_output(self) -> bool:
        return self._output
