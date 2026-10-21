import math
from typing import Optional

from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.readings import ChannelReading


class SimSisBiasChannel(Channel):
    """SIS junction biased by voltage: smooth current step at the gap."""

    instrument: "SimSisBlock"

    def __init__(self, instrument: "SimSisBlock", key: str):
        super().__init__(instrument, key)
        self._voltage = 0.0
        # Same knobs as the real driver; an ideal simulated circuit has no offset
        self.offset_voltage = 0.0
        self.offset_current = 0.0
        self.calibration = None

    def set_voltage(self, voltage: float) -> None:
        if abs(voltage) > self.instrument.max_voltage:
            raise InstrumentResponseError(
                f"{self.name}: voltage {voltage} V out of range"
            )
        self._voltage = voltage

    def get_voltage(self) -> float:
        return self._voltage

    def read_voltage(self) -> float:
        return self._voltage

    def read_current(self) -> float:
        return self.instrument.iv_current(self._voltage)

    def measure(self) -> ChannelReading:
        return ChannelReading(self.read_voltage(), self.read_current())

    def write_calibration(self, coefficients: dict) -> str:
        self.calibration = dict(coefficients)
        return "OK"

    def set_voltage_precise(self, voltage: float, **kwargs) -> float:
        self.set_voltage(voltage)
        return self._voltage


class SimSisCtrlChannel(Channel):
    def __init__(self, instrument: "SimSisBlock", key: str):
        super().__init__(instrument, key)
        self._current = 0.0

    def set_current(self, current: float) -> None:
        self._current = current

    def get_current(self) -> float:
        return self._current


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
        self._ctrl = {}

    def identify(self) -> str:
        return "THZDAQ,SimSisBlock,0,1.0"

    def ctrl(self, device: str) -> SimSisCtrlChannel:
        if device not in self.channel_keys:
            raise ConfigurationError(f"{self.name} has no device {device!r}")
        if device not in self._ctrl:
            self._ctrl[device] = SimSisCtrlChannel(self, device)
        return self._ctrl[device]

    def iv_current(self, voltage: float) -> float:
        step = 1 / (1 + math.exp(-(abs(voltage) - self.gap_voltage) / self.gap_width))
        return (
            voltage / self.subgap_resistance + voltage / self.normal_resistance * step
        )
