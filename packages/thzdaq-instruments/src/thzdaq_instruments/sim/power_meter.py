import random
from typing import Callable, Optional

from thzdaq_instruments.instrument import Instrument


class SimPowerMeter(Instrument):
    """Reads `power` (dBm) or, when given, the value of `model()`.

    The model lets a simulated bench couple instruments, e.g. power that depends
    on the chopper position or the IF filter frequency.
    """

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        power: float = -30.0,
        model: Optional[Callable[[], float]] = None,
        noise: float = 0.0,  # dB, standard deviation
        seed: Optional[int] = None,
    ):
        super().__init__(name=name)
        self.power = power
        self.model = model
        self.noise = noise
        self._random = random.Random(seed)

    def identify(self) -> str:
        return "THZDAQ,SimPowerMeter,0,1.0"

    def read_power(self) -> float:
        value = self.model() if self.model is not None else self.power
        if self.noise:
            value += self._random.gauss(0.0, self.noise)
        return value
