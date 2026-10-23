from typing import List, Optional

from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.sim.lively import Wobble, still
from thzdaq_instruments.units import PSI, celsius_to_kelvin


class SimVacuumGauge(Instrument):
    def __init__(self, *, name: Optional[str] = None, pressure: float = 1e-4):
        super().__init__(name=name)
        self.pressure = pressure  # Pa
        self.wobble = still

    def liven(self) -> None:
        self.wobble = Wobble(0.05, 0.01, period=120.0)  # relative

    def identify(self) -> str:
        return "THZDAQ,SimVacuumGauge,0,1.0"

    def read_pressure(self) -> float:
        return self.pressure * (1 + self.wobble())


class SimCompressor(Instrument):
    def __init__(self, *, name: Optional[str] = None):
        super().__init__(name=name)
        self.running = False
        self.wobble = [still] * 5

    def liven(self) -> None:
        self.wobble = [Wobble(0.5, 0.05) for _ in range(4)] + [Wobble(0.01, 2e-3)]

    def identify(self) -> str:
        return "THZDAQ,SimCompressor,0,1.0"

    def turn_on(self) -> None:
        self.running = True

    def turn_off(self) -> None:
        self.running = False

    def read_temperatures(self) -> List[float]:
        celsius = (60.0, 25.0, 20.0, 0.0) if self.running else (22.0, 21.0, 20.0, 0.0)
        return [celsius_to_kelvin(c) + w() for c, w in zip(celsius, self.wobble)]

    def read_pressures(self) -> List[float]:
        return [(280.0 if self.running else 230.0) * PSI * (1 + self.wobble[4]())]
