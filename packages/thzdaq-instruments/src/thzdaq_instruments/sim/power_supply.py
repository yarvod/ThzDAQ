from typing import Dict, Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.readings import ChannelReading


class SimSupplyChannel(Channel):
    """Output into a resistive load with constant voltage / current limit."""

    instrument: "SimPowerSupply"

    def __init__(self, instrument: "SimPowerSupply", key: int):
        super().__init__(instrument, key)
        self._output = False
        self._voltage = 0.0
        self._current = instrument.max_current
        self.load_resistance = instrument.load_resistances.get(key, 100.0)  # Ohm

    def set_output(self, value: bool) -> None:
        self._output = bool(value)

    def get_output(self) -> bool:
        return self._output

    def set_voltage(self, voltage: float) -> None:
        if not 0 <= voltage <= self.instrument.max_voltage:
            raise InstrumentResponseError(
                f"{self.name}: voltage {voltage} V out of range"
            )
        self._voltage = voltage

    def get_voltage(self) -> float:
        return self._voltage

    def set_current(self, current: float) -> None:
        if not 0 <= current <= self.instrument.max_current:
            raise InstrumentResponseError(
                f"{self.name}: current {current} A out of range"
            )
        self._current = current

    def get_current(self) -> float:
        return self._current

    def measure(self) -> ChannelReading:
        if not self._output:
            return ChannelReading(0.0, 0.0)
        current = self._voltage / self.load_resistance
        if current <= self._current:
            return ChannelReading(self._voltage, current)
        return ChannelReading(self._current * self.load_resistance, self._current)


class SimPowerSupply(Instrument):
    channel_class = SimSupplyChannel
    channel_keys = (1, 2, 3)

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        max_voltage: float = 30.0,
        max_current: float = 3.0,
        load_resistances: Optional[Dict[int, float]] = None,
    ):
        super().__init__(name=name)
        self.max_voltage = max_voltage
        self.max_current = max_current
        self.load_resistances = load_resistances or {}

    def identify(self) -> str:
        return "THZDAQ,SimPowerSupply,0,1.0"
