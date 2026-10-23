from typing import Dict, Optional

from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.sim.lively import Wobble, still


class SimTemperatureInput(Channel):
    instrument: "SimTemperatureController"

    def read_temperature(self) -> float:
        temperature = self.instrument.temperatures[self.key]
        return temperature * (1 + self.instrument.wobble[self.key]())


class SimTemperatureController(Instrument):
    channel_class = SimTemperatureInput
    channel_keys = ("A", "B", "C", "D")

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        temperatures: Optional[Dict[str, float]] = None
    ):
        super().__init__(name=name)
        self.temperatures = {"A": 4.2, "B": 40.0, "C": 77.0, "D": 300.0}
        self.temperatures.update(temperatures or {})
        self.wobble = {key: still for key in self.channel_keys}

    def liven(self) -> None:
        self.wobble = {key: Wobble(5e-3, 5e-4) for key in self.channel_keys}

    def identify(self) -> str:
        return "THZDAQ,SimTemperatureController,0,1.0"
