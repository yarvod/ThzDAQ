from abc import ABC, abstractmethod
from typing import ClassVar, Tuple

from thzdaq_instruments.instrument import Channel, ScpiInstrument
from thzdaq_instruments.readings import ChannelReading


class SupplyChannel(Channel):
    """One output of a power supply.

    Implements Switchable, VoltageSource, CurrentSource and VoltageCurrentMeter
    once for every vendor: the instrument provides the SCPI primitives.
    """

    instrument: "ScpiPowerSupply"

    def set_output(self, value: bool) -> None:
        self.instrument._set_output(self.key, bool(value))

    def get_output(self) -> bool:
        return self.instrument._get_output(self.key)

    def set_voltage(self, voltage: float) -> None:
        self.instrument._set_voltage(self.key, voltage)

    def get_voltage(self) -> float:
        return self.instrument._get_voltage(self.key)

    def set_current(self, current: float) -> None:
        self.instrument._set_current(self.key, current)

    def get_current(self) -> float:
        return self.instrument._get_current(self.key)

    def measure(self) -> ChannelReading:
        return self.instrument._measure(self.key)


class ScpiPowerSupply(ScpiInstrument, ABC):
    """Template for multi-channel supplies: vendors implement the primitives below."""

    channel_class = SupplyChannel
    channel_keys: ClassVar[Tuple[int, ...]] = (1,)

    @abstractmethod
    def _set_output(self, channel: int, value: bool) -> None:
        ...

    @abstractmethod
    def _get_output(self, channel: int) -> bool:
        ...

    @abstractmethod
    def _set_voltage(self, channel: int, voltage: float) -> None:
        ...

    @abstractmethod
    def _get_voltage(self, channel: int) -> float:
        ...

    @abstractmethod
    def _set_current(self, channel: int, current: float) -> None:
        ...

    @abstractmethod
    def _get_current(self, channel: int) -> float:
        ...

    @abstractmethod
    def _measure(self, channel: int) -> ChannelReading:
        ...

    def reset(self) -> None:
        self.write("*RST")
