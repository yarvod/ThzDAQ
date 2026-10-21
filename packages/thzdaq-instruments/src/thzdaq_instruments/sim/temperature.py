from typing import Dict, Optional

from thzdaq_instruments.instrument import Channel, Instrument


class SimTemperatureInput(Channel):
    instrument: "SimTemperatureController"

    def read_temperature(self) -> float:
        return self.instrument.temperatures[self.key]


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

    def identify(self) -> str:
        return "THZDAQ,SimTemperatureController,0,1.0"
