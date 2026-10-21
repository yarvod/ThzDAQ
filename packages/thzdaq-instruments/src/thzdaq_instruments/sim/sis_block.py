import math
from typing import Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.readings import ChannelReading


class SimSisBiasChannel(Channel):
    """SIS junction biased by voltage: smooth current step at the gap."""

    instrument: "SimSisBlock"

    def __init__(self, instrument: "SimSisBlock", key: str):
        super().__init__(instrument, key)
        self._voltage = 0.0

    def set_voltage(self, voltage: float) -> None:
        if abs(voltage) > self.instrument.max_voltage:
            raise InstrumentResponseError(
                f"{self.name}: voltage {voltage} V out of range"
            )
        self._voltage = voltage

    def get_voltage(self) -> float:
        return self._voltage

    def measure(self) -> ChannelReading:
        return ChannelReading(self._voltage, self.instrument.iv_current(self._voltage))


class SimSisBlock(Instrument):
    channel_class = SimSisBiasChannel
    channel_keys = ("DEV1", "DEV2", "DEV3", "DEV4")

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        gap_voltage: float = 2.8e-3,  # V
        normal_resistance: float = 20.0,  # Ohm
        subgap_resistance: float = 500.0,  # Ohm
        gap_width: float = 0.05e-3,  # V
        max_voltage: float = 30e-3,  # V
    ):
        super().__init__(name=name)
        self.gap_voltage = gap_voltage
        self.normal_resistance = normal_resistance
        self.subgap_resistance = subgap_resistance
        self.gap_width = gap_width
        self.max_voltage = max_voltage

    def identify(self) -> str:
        return "THZDAQ,SimSisBlock,0,1.0"

    def iv_current(self, voltage: float) -> float:
        step = 1 / (1 + math.exp(-(abs(voltage) - self.gap_voltage) / self.gap_width))
        return (
            voltage / self.subgap_resistance + voltage / self.normal_resistance * step
        )
