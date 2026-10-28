import math
import random
from typing import Callable, Optional

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.quantities import POWER_METER_QUANTITIES, POWER_UNITS
from thzdaq_instruments.sim.lively import Wobble, still

# The receiver a simulated bench measures with its hot and cold loads
T_COLD, T_HOT = 77.0, 300.0  # K
T_RECEIVER = 60.0  # K


def load_power(power: float, load: Optional[str]) -> float:
    """Power with a load in the beam, P ∝ T_load + T_receiver: `power` with the
    cold load (or none), more with the hot one (Y ≈ 4.2 dB, Tn = T_RECEIVER)."""
    if load != "hot":
        return power
    return power + 10 * math.log10((T_HOT + T_RECEIVER) / (T_COLD + T_RECEIVER))


class SimPowerMeter(Instrument):
    """Reads `power` (dBm) or, when given, the value of `model()`.

    The model lets a simulated bench couple instruments, e.g. power that depends
    on the chopper position or the IF filter frequency. `load_position()`, when
    given, says where the load of the bench is ("hot", "cold"): the hot one adds
    power as a receiver would see it (load_power). Has the settings of an
    R&S NRX (display unit, averaging, filter and aperture time, limits).
    """

    quantities = POWER_METER_QUANTITIES

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
        self.load_position: Optional[Callable[[], Optional[str]]] = None
        self.noise = noise
        self._random = random.Random(seed)
        self.wobble = still
        self.unit = "DBM"
        self.averaging = False
        self.filter_time = 0.05  # s
        self.aperture_time = 0.05  # s
        self.lower_limit = -60.0
        self.upper_limit = 30.0
        self._last = None

    def liven(self) -> None:
        self.wobble = Wobble(drift=0.5, noise=0.05)  # dB

    def identify(self) -> str:
        return "THZDAQ,SimPowerMeter,0,1.0"

    def read_power(self) -> float:
        value = self.model() if self.model is not None else self.power
        if self.load_position is not None:
            value = load_power(value, self.load_position())
        if self.noise:
            value += self._random.gauss(0.0, self.noise)
        self._last = value + self.wobble()
        return self._last

    # NRX settings
    def get_units(self) -> str:
        return self.unit

    def set_units(self, unit: str) -> None:
        if unit not in POWER_UNITS:
            raise ConfigurationError(f"Unsupported power unit {unit!r}")
        self.unit = unit

    def fetch(self) -> float:
        """The last reading in the display unit."""
        dbm = self.read_power() if self._last is None else self._last
        if self.unit == "W":
            return 10 ** (dbm / 10) / 1000
        if self.unit == "DBUV":
            return dbm + 107.0
        return dbm

    def get_averaging(self) -> bool:
        return self.averaging

    def set_averaging(self, value: bool) -> None:
        self.averaging = bool(value)

    def get_filter_time(self) -> float:
        return self.filter_time

    def set_filter_time(self, seconds: float) -> None:
        self.filter_time = float(seconds)

    def get_aperture_time(self) -> float:
        return self.aperture_time

    def set_aperture_time(self, seconds: float) -> None:
        self.aperture_time = float(seconds)

    def get_lower_limit(self) -> float:
        return self.lower_limit

    def set_lower_limit(self, value: float) -> None:
        self.lower_limit = float(value)

    def get_upper_limit(self) -> float:
        return self.upper_limit

    def set_upper_limit(self, value: float) -> None:
        self.upper_limit = float(value)
