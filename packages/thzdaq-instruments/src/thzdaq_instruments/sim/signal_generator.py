from typing import Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.quantities import GENERATOR_QUANTITIES


class SimSignalGenerator(Instrument):
    """Generator with the configuration of an E8247C (multiplier, OEM head).

    Like the real one, frequencies are the displayed ones: with a multiplier
    set, set_frequency(223 GHz) puts 223/18 GHz out of the generator.
    """

    quantities = GENERATOR_QUANTITIES

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        min_frequency: float = 250e3,
        max_frequency: float = 40e9,
        min_power: float = -135.0,
        max_power: float = 25.0,
        frequency_multiplier: float = 1.0,
    ):
        super().__init__(name=name)
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.min_power = min_power
        self.max_power = max_power
        self.frequency_multiplier = frequency_multiplier
        self._frequency = min_frequency * frequency_multiplier
        self._power = min_power
        self._output = False
        self.oem_state = "OFF"
        self.oem_start = 219.6e9
        self.oem_stop = 325.8e9
        self.oem_multiplier = 18.0

    def identify(self) -> str:
        return "THZDAQ,SimSignalGenerator,0,1.0"

    def set_frequency(self, frequency: float) -> None:
        output = frequency / self.frequency_multiplier
        if not self.min_frequency <= output <= self.max_frequency:
            raise InstrumentResponseError(
                f"{self.name}: frequency {frequency} Hz out of range"
            )
        self._frequency = frequency

    def get_frequency(self) -> float:
        return self._frequency

    def set_frequency_multiplier(self, value: float) -> None:
        self._frequency = self._frequency / self.frequency_multiplier * value
        self.frequency_multiplier = float(value)

    def get_frequency_multiplier(self) -> float:
        return self.frequency_multiplier

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

    # OEM head, remembered only
    def set_oem_state(self, value: str) -> None:
        self.oem_state = value

    def get_oem_state(self) -> str:
        return self.oem_state

    def set_oem_frequency_start(self, frequency: float) -> None:
        self.oem_start = frequency

    def get_oem_frequency_start(self) -> float:
        return self.oem_start

    def set_oem_frequency_stop(self, frequency: float) -> None:
        self.oem_stop = frequency

    def get_oem_frequency_stop(self) -> float:
        return self.oem_stop

    def set_oem_multiplier(self, value: float) -> None:
        self.oem_multiplier = float(value)

    def get_oem_multiplier(self) -> float:
        return self.oem_multiplier
