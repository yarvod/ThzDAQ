from typing import Dict, Hashable, Optional

from thzdaq_instruments.capabilities import Thermometer
from thzdaq_instruments.instrument import Channel
from thzdaq_instruments.sim.lively import Wobble, still
from thzdaq_instruments.sim.base import SimInstrument
from thzdaq_instruments.temperature_controller import (
    CONTROL_INPUTS,
    CONTROL_MODES,
    HEATER_QUANTITIES,
    HEATER_RANGES,
    HEATER_STATES,
    HEATERS,
    INPUTS,
    OutputMode,
    Pid,
    number_of,
)

RANGE_OFF = HEATER_RANGES[0]
OFF, _, _, OPEN_LOOP = CONTROL_MODES


class SimTemperatureInput(Channel, Thermometer):
    instrument: "SimTemperatureController"

    def read_temperature(self) -> float:
        temperature = self.instrument.temperatures[self.key]
        return temperature * (1 + self.instrument.wobble[self.key]())


class SimHeaterOutput(Channel):
    """A heater output that drives nothing: in a loop its output follows the
    error of its input, in open loop it is the manual output."""

    instrument: "SimTemperatureController"
    quantities = HEATER_QUANTITIES

    def __init__(self, instrument: "SimTemperatureController", key: Hashable):
        super().__init__(instrument, key)
        self.range = RANGE_OFF
        self.mode = OutputMode(OFF, CONTROL_INPUTS[0])
        self.setpoint = 0.0
        self.manual = 0.0
        self.pid = Pid(50.0, 20.0, 0.0)

    def set_setpoint(self, kelvin: float) -> None:
        self.setpoint = float(kelvin)

    def get_setpoint(self) -> float:
        return self.setpoint

    def set_range(self, name: str) -> None:
        number_of(HEATER_RANGES, name)
        self.range = name

    def get_range(self) -> str:
        return self.range

    def get_output(self) -> float:
        if self.range == RANGE_OFF or self.mode.mode == OFF:
            return 0.0
        if self.mode.mode == OPEN_LOOP:
            return self.manual
        if self.mode.input not in self.instrument.temperatures:
            return 0.0
        error = self.setpoint - self.instrument.temperatures[self.mode.input]
        return min(100.0, max(0.0, self.pid.p * error))

    def set_manual_output(self, percent: float) -> None:
        self.manual = float(percent)

    def get_manual_output(self) -> float:
        return self.manual

    def get_status(self) -> str:
        return HEATER_STATES[0]

    def set_mode(self, mode: OutputMode) -> None:
        number_of(CONTROL_MODES, mode.mode)
        number_of(CONTROL_INPUTS, mode.input)
        self.mode = mode

    def get_mode(self) -> OutputMode:
        return self.mode

    def set_pid(self, pid: Pid) -> None:
        self.pid = pid

    def get_pid(self) -> Pid:
        return self.pid


class SimTemperatureController(SimInstrument):
    driver_key = "sim.temperature_controller"
    device_type = "temperature_controller"
    channel_class = SimTemperatureInput
    channel_keys = INPUTS
    extra_channels = {key: SimHeaterOutput for key in HEATERS}

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
