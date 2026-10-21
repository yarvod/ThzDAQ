from typing import Literal

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.transport.base import PROLOGIX, ConnectionSpec

OemState = Literal["ON", "OFF", "NONE", "REAR", "FRONT"]


class AgilentE8247C(ScpiInstrument):
    """Agilent/Keysight PSG E8247C, usually GPIB behind Prologix.

    Frequencies are the ones the instrument displays: with a frequency
    multiplier or an OEM head set on the instrument they include it.
    """

    ATTENUATOR_STEPS = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90)  # dB
    MAX_AMPLITUDE = 25.0  # dBm

    @staticmethod
    def connection(host: str = "169.254.156.103", gpib: int = 19) -> ConnectionSpec:
        return ConnectionSpec(PROLOGIX, host=host, gpib=gpib)

    def test(self) -> bool:
        return "Agilent" in self.identify()

    def reset(self) -> None:
        self.write("*RST")

    # Switchable
    def set_output(self, value: bool) -> None:
        self.write(f"OUTP {1 if value else 0}")

    def get_output(self) -> bool:
        return self.query_bool("OUTP?")

    # FrequencySource
    def set_frequency(self, frequency: float) -> None:
        self.write(f":FREQ:FIX {frequency}")

    def get_frequency(self) -> float:
        return self.query_float(":FREQ:FIX?")

    def set_frequency_multiplier(self, value: float) -> None:
        self.write(f":FREQ:MULT {value}")

    def get_frequency_multiplier(self) -> float:
        return self.query_float(":FREQ:MULT?")

    # PowerLevel
    def set_power(self, power: float) -> None:
        self.write(f"POW {power}dBm")

    def get_power(self) -> float:
        return self.query_float("POW?")

    # Manual attenuator + ALC control, as used for the LO chain
    def set_attenuation(self, value: float) -> None:
        self.write(f":POW:ATT {value}")

    def get_attenuation(self) -> float:
        return self.query_float(":POW:ATT?")

    def set_alc_level(self, value: float) -> None:
        self.write(f":POW:ALC:LEV {value}")

    def get_alc_level(self) -> float:
        return self.query_float(":POW:ALC:LEV?")

    def set_amplitude(self, value: float) -> None:
        """Output level through attenuator steps plus ALC, dBm."""
        if value > self.MAX_AMPLITUDE:
            raise ConfigurationError(f"Amplitude above {self.MAX_AMPLITUDE} dBm")
        index = int(round((abs(value) - 10) / 10))
        if index < 0 or value > 0:
            index = 0
        index = min(index, len(self.ATTENUATOR_STEPS) - 1)
        attenuation = self.ATTENUATOR_STEPS[index]
        with self.transport.transaction():
            self.set_alc_level(0)
            self.set_attenuation(attenuation)
            self.set_alc_level(value + attenuation)

    def get_amplitude(self) -> float:
        with self.transport.transaction():
            return self.get_alc_level() - self.get_attenuation()

    # OEM frequency extension head
    def set_oem_state(self, value: OemState) -> None:
        self.write(f":SYST:OEMH:SEL {value}")

    def get_oem_state(self) -> str:
        return self.query(":SYST:OEMH:SEL?")

    def set_oem_frequency_range(self, start: float, stop: float) -> None:
        self.write(f":SYST:OEMH:FREQ:STAR {start}")
        self.write(f":SYST:OEMH:FREQ:STOP {stop}")

    def set_oem_multiplier(self, value: float) -> None:
        self.write(f":SYST:OEMH:FREQ:MULT {value}")

    def get_oem_multiplier(self) -> float:
        return self.query_float(":SYST:OEMH:FREQ:MULT?")
