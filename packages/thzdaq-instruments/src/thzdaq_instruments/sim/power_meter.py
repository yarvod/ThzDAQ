import math
import random
from typing import Any, Callable, Optional

from thzdaq_instruments.actions import POWER_SENSOR_ACTIONS
from thzdaq_instruments.capabilities import PowerDetector
from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.sim.base import SimInstrument
from thzdaq_instruments.quantities import (
    MEASUREMENT_RATES,
    POWER_METER_QUANTITIES,
    POWER_UNITS,
    U2000_QUANTITIES,
)
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


class SimDetector(SimInstrument, PowerDetector):
    """What every simulated power meter measures: `power` (dBm) or, when
    given, the value of `model()`.

    The model lets a simulated bench couple instruments, e.g. power that depends
    on the chopper position or the IF filter frequency. `load_position()`, when
    given, says where the load of the bench is ("hot", "cold"): the hot one adds
    power as a receiver would see it (load_power). The settings are those of the
    meter simulated (subclasses).
    """

    device_type = "power_meter"

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
        self._last: Optional[float] = None  # dBm, the last reading

    def liven(self) -> None:
        self.wobble = Wobble(drift=0.5, noise=0.05)  # dB

    def identify(self) -> str:
        return f"THZDAQ,{type(self).__name__},0,1.0"

    def read_power(self) -> float:
        value = self.model() if self.model is not None else self.power
        if self.load_position is not None:
            value = load_power(value, self.load_position())
        if self.noise:
            value += self._random.gauss(0.0, self.noise)
        self._last = value + self.wobble()
        return self._last


class SimPowerMeter(SimDetector):
    """The R&S NRX simulated: display unit, averaging, filter and aperture
    time, limits."""

    driver_key = "sim.power_meter"

    quantities = POWER_METER_QUANTITIES

    def __init__(self, **detector: Any):
        super().__init__(**detector)
        self.unit = "DBM"
        self.averaging = False
        self.filter_time = 0.05  # s
        self.aperture_time = 0.05  # s
        self.lower_limit = -60.0
        self.upper_limit = 30.0

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


class SimU2000(SimDetector):
    """A Keysight U2000 USB power sensor simulated: its offset adds to the
    power, its averaging settings couple as the sensor's do, a zero does
    nothing."""

    quantities = U2000_QUANTITIES
    actions = POWER_SENSOR_ACTIONS

    def __init__(self, **detector: Any):
        super().__init__(**detector)
        self.frequency = 50e6  # Hz, as after *RST
        self.temperature = 300.0  # K
        self.averaging = True
        self.averaging_auto = True
        self.averaging_count = 4
        self.measurement_rate = "NORM"
        self.offset = 0.0  # dB

    def read_power(self) -> float:
        return super().read_power() + self.offset

    def set_frequency(self, frequency: float) -> None:
        self.frequency = float(frequency)

    def get_frequency(self) -> float:
        return self.frequency

    def read_temperature(self) -> float:
        return self.temperature

    def set_averaging(self, value: bool) -> None:
        self.averaging = bool(value)

    def get_averaging(self) -> bool:
        return self.averaging

    def set_averaging_auto(self, value: bool) -> None:
        self.averaging_auto = bool(value)
        self.averaging = self.averaging or self.averaging_auto

    def get_averaging_auto(self) -> bool:
        return self.averaging_auto

    def set_averaging_count(self, count: int) -> None:
        self.averaging_count = int(count)
        self.averaging_auto, self.averaging = False, True

    def get_averaging_count(self) -> int:
        return self.averaging_count

    def set_measurement_rate(self, rate: str) -> None:
        if rate not in MEASUREMENT_RATES:
            raise ConfigurationError(f"Unsupported measurement rate {rate!r}")
        self.measurement_rate = rate

    def get_measurement_rate(self) -> str:
        return self.measurement_rate

    def set_offset(self, db: float) -> None:
        self.offset = float(db)

    def get_offset(self) -> float:
        return self.offset

    def zero(self) -> None:
        pass

    def zero_external(self) -> None:
        pass
