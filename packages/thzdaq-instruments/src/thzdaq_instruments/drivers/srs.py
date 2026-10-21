from typing import Literal, Tuple

from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.transport.base import PROLOGIX, ConnectionSpec

Output = Literal["X", "Y", "R", "THETA"]
OUTPUTS = {"X": 1, "Y": 2, "R": 3, "THETA": 4}

# OFLT index -> time constant, s
TIME_CONSTANTS = tuple(
    base * 10**exponent for exponent in range(-5, 5) for base in (1, 3)
)
# SENS index -> full scale, V
SENSITIVITIES = tuple(
    base * 10**exponent for exponent in range(-9, 1) for base in (2, 5, 10)
)[:27]


class StanfordSR830(ScpiInstrument):
    """SRS SR830 lock-in amplifier, usually GPIB behind Prologix."""

    @staticmethod
    def connection(host: str = "169.254.156.103", gpib: int = 8) -> ConnectionSpec:
        return ConnectionSpec(PROLOGIX, host=host, gpib=gpib)

    def test(self) -> bool:
        return "SR830" in self.identify()

    def read(self, output: Output = "R") -> float:
        """V for X, Y, R; degrees for THETA."""
        return self.query_float(f"OUTP? {OUTPUTS[output]}")

    def read_xy(self) -> Tuple[float, float]:
        """X and Y sampled at the same instant."""
        response = self.query("SNAP? 1,2")
        try:
            x, y = (float(v) for v in response.split(","))
        except ValueError as e:
            raise InstrumentResponseError(f"SNAP? answered {response!r}") from e
        return x, y

    def set_reference_frequency(self, frequency: float) -> None:
        self.write(f"FREQ {frequency}")

    def get_reference_frequency(self) -> float:
        return self.query_float("FREQ?")

    def set_phase(self, degrees: float) -> None:
        self.write(f"PHAS {degrees}")

    def get_phase(self) -> float:
        return self.query_float("PHAS?")

    def set_amplitude(self, volts: float) -> None:
        """Sine output amplitude, V rms"""
        self.write(f"SLVL {volts}")

    def get_amplitude(self) -> float:
        return self.query_float("SLVL?")

    def set_time_constant(self, seconds: float) -> float:
        """Nearest supported time constant; returns it."""
        index = min(
            range(len(TIME_CONSTANTS)), key=lambda i: abs(TIME_CONSTANTS[i] - seconds)
        )
        self.write(f"OFLT {index}")
        return TIME_CONSTANTS[index]

    def get_time_constant(self) -> float:
        return TIME_CONSTANTS[self.query_int("OFLT?")]

    def set_sensitivity(self, volts: float) -> float:
        """Smallest full scale range that fits `volts`; returns it."""
        for index, value in enumerate(SENSITIVITIES):
            if value >= volts:
                self.write(f"SENS {index}")
                return value
        raise ConfigurationError(f"Sensitivity above {SENSITIVITIES[-1]} V")

    def get_sensitivity(self) -> float:
        return SENSITIVITIES[self.query_int("SENS?")]

    def auto_gain(self) -> None:
        self.write("AGAN")

    def auto_phase(self) -> None:
        self.write("APHS")
