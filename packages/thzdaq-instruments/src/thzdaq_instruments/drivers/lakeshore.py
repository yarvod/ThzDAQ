from dataclasses import dataclass
from typing import Dict, Literal, Optional

from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import Channel, ScpiInstrument
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec

HeaterRange = Literal[0, 1, 2, 3]  # off, low, medium, high
OUTPUT_MODES = {
    0: "off",
    1: "closed loop PID",
    2: "zone",
    3: "open loop",
    4: "monitor out",
    5: "warmup supply",
}


class TemperatureInput(Channel):
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


@dataclass(frozen=True)
class OutputMode:
    mode: int  # see OUTPUT_MODES
    input: int  # 0 = none, 1 = A, 2 = B, 3 = C, 4 = D
    powerup_enable: bool


class HeaterOutput:
    """Control output 1-4 (1 and 2 are heaters)."""

    def __init__(self, instrument: "LakeShore336", output: int):
        self.instrument = instrument
        self.output = output

    def set_setpoint(self, kelvin: float) -> None:
        self.instrument.write(f"SETP {self.output},{kelvin}")

    def get_setpoint(self) -> float:
        return self.instrument.query_float(f"SETP? {self.output}")

    def set_range(self, value: HeaterRange) -> None:
        self.instrument.write(f"RANGE {self.output},{int(value)}")

    def get_range(self) -> int:
        return self.instrument.query_int(f"RANGE? {self.output}")

    def get_output(self) -> float:
        """Heater output, %"""
        return self.instrument.query_float(f"HTR? {self.output}")

    def set_manual_output(self, percent: float) -> None:
        self.instrument.write(f"MOUT {self.output},{percent}")

    def get_manual_output(self) -> float:
        return self.instrument.query_float(f"MOUT? {self.output}")

    def get_status(self) -> int:
        """0 = no error, 1 = open load, 2 = short"""
        return self.instrument.query_int(f"HTRST? {self.output}")

    def setup(self, setup: HeaterSetup) -> None:
        self.instrument.write(
            f"HTRSET {self.output},{setup.resistance},{setup.max_current},"
            f"{setup.max_user_current},{setup.display}"
        )

    def get_setup(self) -> HeaterSetup:
        fields = self.instrument.query(f"HTRSET? {self.output}").split(",")
        try:
            return HeaterSetup(
                int(fields[0]), int(fields[1]), float(fields[2]), int(fields[3])
            )
        except (IndexError, ValueError) as e:
            raise InstrumentResponseError(f"HTRSET? answered {fields!r}") from e

    def set_mode(self, mode: OutputMode) -> None:
        # The legacy driver had an empty set_out_mode, the mode was never sent
        if mode.mode not in OUTPUT_MODES:
            raise ConfigurationError(f"Unknown output mode {mode.mode}")
        self.instrument.write(
            f"OUTMODE {self.output},{mode.mode},{mode.input},{int(mode.powerup_enable)}"
        )

    def get_mode(self) -> OutputMode:
        fields = self.instrument.query(f"OUTMODE? {self.output}").split(",")
        try:
            return OutputMode(int(fields[0]), int(fields[1]), fields[2].strip() == "1")
        except (IndexError, ValueError) as e:
            raise InstrumentResponseError(f"OUTMODE? answered {fields!r}") from e


class LakeShore336(ScpiInstrument):
    """LakeShore 336 temperature controller; inputs via channel("A".."D")."""

    channel_class = TemperatureInput
    channel_keys = ("A", "B", "C", "D")

    def __init__(self, transport, *, name: Optional[str] = None):
        super().__init__(transport, name=name)
        self._heaters: Dict[int, HeaterOutput] = {}

    @staticmethod
    def connection(host: str = "169.254.0.56", port: int = 7777) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return self.identify().startswith("LSCI,MODEL336")

    def heater(self, output: int) -> HeaterOutput:
        if output not in (1, 2, 3, 4):
            raise ConfigurationError(f"{self.name} has no output {output}")
        if output not in self._heaters:
            self._heaters[output] = HeaterOutput(self, output)
        return self._heaters[output]

    def set_remote_mode(self, mode: Literal[0, 1, 2]) -> None:
        """0 = local, 1 = remote, 2 = remote with local lockout"""
        self.write(f"MODE {mode}")

    def get_remote_mode(self) -> int:
        return self.query_int("MODE?")
