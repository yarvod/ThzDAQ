from dataclasses import dataclass
from typing import Hashable, List, Literal, Sequence

from thzdaq_instruments.capabilities import Thermometer
from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import Channel, ScpiInstrument
from thzdaq_instruments.temperature_controller import (
    CONTROL_INPUTS,
    CONTROL_MODES,
    HEATER_LIMITS,
    HEATER_QUANTITIES,
    HEATER_RANGES,
    HEATER_STATES,
    HEATERS,
    INPUTS,
    OutputMode,
    Pid,
    number_of,
)
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec


class TemperatureInput(Channel, Thermometer):
    """Sensor input A-D: Thermometer."""

    instrument: "LakeShore336"

    def read_temperature(self) -> float:
        return self.instrument.query_float(f"KRDG? {self.key}")

    def read_sensor(self) -> float:
        """Raw sensor units (Ohm or V)."""
        return self.instrument.query_float(f"SRDG? {self.key}")


@dataclass(frozen=True)
class HeaterSetup:
    resistance: int  # 1 = 25 Ohm, 2 = 50 Ohm
    max_current: int  # 0 = user, 1 = 0.707 A, 2 = 1 A, 3 = 1.141 A, 4 = 2 A
    max_user_current: float  # A
    display: int  # 1 = current, 2 = power


def _fields(answer: str, count: int, command: str) -> List[str]:
    fields = [field.strip() for field in answer.split(",")]
    if len(fields) != count:
        raise InstrumentResponseError(f"{command} answered {answer!r}")
    return fields


def _name(names: Sequence[str], number: str, command: str) -> str:
    """The name of a setting the instrument answered by its number."""
    try:
        return names[int(float(number))]
    except (IndexError, ValueError) as e:
        raise InstrumentResponseError(f"{command} answered {number!r}") from e


class HeaterOutput(Channel):
    """Heater output 1 or 2 (channel heater1, heater2)."""

    instrument: "LakeShore336"
    quantities = HEATER_QUANTITIES

    def __init__(self, instrument: "LakeShore336", key: Hashable):
        super().__init__(instrument, key)
        self.output = HEATERS[key]

    def _query(self, command: str) -> str:
        return self.instrument.query(f"{command}? {self.output}")

    def set_setpoint(self, kelvin: float) -> None:
        self.instrument.write(f"SETP {self.output},{kelvin}")

    def get_setpoint(self) -> float:
        return self.instrument.query_float(f"SETP? {self.output}")

    def set_range(self, name: str) -> None:
        """One of HEATER_RANGES: off, or how much power it may give."""
        number = number_of(HEATER_RANGES, name)
        self.instrument.write(f"RANGE {self.output},{number}")

    def get_range(self) -> str:
        return _name(HEATER_RANGES, self._query("RANGE"), "RANGE?")

    def get_output(self) -> float:
        """Heater output, %"""
        return self.instrument.query_float(f"HTR? {self.output}")

    def set_manual_output(self, percent: float) -> None:
        self.instrument.write(f"MOUT {self.output},{percent}")

    def get_manual_output(self) -> float:
        return self.instrument.query_float(f"MOUT? {self.output}")

    def get_status(self) -> str:
        """One of HEATER_STATES."""
        return _name(HEATER_STATES, self._query("HTRST"), "HTRST?")

    def setup(self, setup: HeaterSetup) -> None:
        self.instrument.write(
            f"HTRSET {self.output},{setup.resistance},{setup.max_current},"
            f"{setup.max_user_current},{setup.display}"
        )

    def get_setup(self) -> HeaterSetup:
        fields = _fields(self._query("HTRSET"), 4, "HTRSET?")
        try:
            return HeaterSetup(
                int(fields[0]), int(fields[1]), float(fields[2]), int(fields[3])
            )
        except ValueError as e:
            raise InstrumentResponseError(f"HTRSET? answered {fields!r}") from e

    def set_mode(self, mode: OutputMode) -> None:
        # The legacy driver had an empty set_out_mode, the mode was never sent
        number = number_of(CONTROL_MODES, mode.mode)
        source = number_of(CONTROL_INPUTS, mode.input)
        self.instrument.write(
            f"OUTMODE {self.output},{number},{source},{int(mode.powerup_enable)}"
        )

    def get_mode(self) -> OutputMode:
        mode, source, powerup = _fields(self._query("OUTMODE"), 3, "OUTMODE?")
        return OutputMode(
            _name(CONTROL_MODES, mode, "OUTMODE?"),
            _name(CONTROL_INPUTS, source, "OUTMODE?"),
            powerup == "1",
        )

    def set_pid(self, pid: Pid) -> None:
        self.instrument.write(f"PID {self.output},{pid.p},{pid.i},{pid.d}")

    def get_pid(self) -> Pid:
        fields = _fields(self._query("PID"), 3, "PID?")
        try:
            return Pid(*(float(field) for field in fields))
        except ValueError as e:
            raise InstrumentResponseError(f"PID? answered {fields!r}") from e


class LakeShore336(ScpiInstrument):
    """LakeShore 336 temperature controller: inputs as channel("A".."D"),
    heater outputs as channel("heater1"), channel("heater2")."""

    driver_key = "lakeshore.336"
    device_type = "temperature_controller"

    channel_class = TemperatureInput
    channel_keys = INPUTS
    extra_channels = {key: HeaterOutput for key in HEATERS}
    channel_limits = {key: HEATER_LIMITS for key in HEATERS}

    @staticmethod
    def connection(host: str = "169.254.0.56", port: int = 7777) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return self.identify().startswith("LSCI,MODEL336")

    def heater(self, output: int) -> HeaterOutput:
        """Heater output 1 or 2."""
        keys = {number: key for key, number in HEATERS.items()}
        if output not in keys:
            raise ConfigurationError(f"{self.name} has no heater output {output}")
        return self.channel(keys[output])

    def set_remote_mode(self, mode: Literal[0, 1, 2]) -> None:
        """0 = local, 1 = remote, 2 = remote with local lockout"""
        self.write(f"MODE {mode}")

    def get_remote_mode(self) -> int:
        return self.query_int("MODE?")
