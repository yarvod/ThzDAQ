from typing import Dict, Optional, Tuple

from thzdaq_instruments.capabilities import (
    CurrentSource,
    OutputProtection,
    Switchable,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Channel
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.sim.lively import Wobble, still
from thzdaq_instruments.sim.base import SimInstrument


class SimPlainSupplyChannel(
    Channel, Switchable, VoltageSource, CurrentSource, VoltageCurrentMeter
):
    """Output into a resistive load with constant voltage / current limit,
    without a protection of its own (as on the HMP2030 and the Keithley 2200)."""

    instrument: "SimPlainPowerSupply"

    def __init__(self, instrument: "SimPlainPowerSupply", key: int):
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
        # The load warms up and cools down a little
        load = self.load_resistance * (1 + self.instrument.wobble())
        current = self._voltage / load
        if current <= self._current:
            return ChannelReading(self._voltage, current)
        return ChannelReading(self._current * load, self._current)


class SimSupplyChannel(SimPlainSupplyChannel, OutputProtection):
    """An output that also switches itself off above its over-voltage
    protection (as on the Rigol DP832A)."""

    def __init__(self, instrument: "SimPlainPowerSupply", key: int):
        super().__init__(instrument, key)
        # Over-voltage and over-current protection levels (V, A), None: off
        self.protection: Tuple[Optional[float], Optional[float]] = (None, None)

    def set_protection(
        self, voltage: Optional[float], current: Optional[float]
    ) -> None:
        if voltage is not None:
            self.protection = (voltage, self.protection[1])
        if current is not None:
            self.protection = (self.protection[0], current)

    def set_voltage(self, voltage: float) -> None:
        super().set_voltage(voltage)
        ovp = self.protection[0]
        if ovp is not None and voltage > ovp:
            self._output = False  # the protection trips


class SimPlainPowerSupply(SimInstrument):
    """A three-output supply whose outputs have no protection of their own."""

    device_type = "power_supply"
    channel_class = SimPlainSupplyChannel
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
        self.wobble = still

    def liven(self) -> None:
        self.wobble = Wobble(2e-3, 2e-4)  # relative

    def identify(self) -> str:
        return f"THZDAQ,{type(self).__name__},0,1.0"


class SimSingleSupply(SimPlainPowerSupply):
    """A one-output supply without protection (as a Keithley 2200)."""

    channel_keys = (1,)


class SimPowerSupply(SimPlainPowerSupply):
    """A three-output supply whose outputs protect themselves (OVP, OCP)."""

    driver_key = "sim.power_supply"
    channel_class = SimSupplyChannel
