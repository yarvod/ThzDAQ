from typing import Any, ClassVar, Dict

from thzdaq_instruments.actions import POWER_SENSOR_ACTIONS
from thzdaq_instruments.capabilities import PowerDetector
from thzdaq_instruments.errors import ConfigurationError, InstrumentError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import (
    CORRECTION_FREQUENCY,
    MEASUREMENT_RATES,
    U2000_QUANTITIES,
)
from thzdaq_instruments.transport.base import VISA, ConnectionSpec, recommendation
from thzdaq_instruments.units import celsius_to_kelvin

# Always dBm and a new, settled measurement, whatever was set before: READ?
# fails while measuring continuously (INIT:CONT ON), and the unit may be W
READ_DBM = "UNIT:POW DBM;:INIT:CONT OFF;:READ?"
# s: READ? answers once the averaging filter is full (auto averaging near the
# bottom of the range: seconds), a zero once it is done
TIMEOUT = 20.0


class KeysightU2000(ScpiInstrument, PowerDetector):
    """Keysight (Agilent) U2000 USB average power sensor, USBTMC over VISA.

    It has no display and forgets its settings when it is plugged in again, so
    the program gives them each time it opens (keeps_settings). A reading waits
    until the averaging filter is full: with auto averaging near the bottom of
    the range that takes seconds. The frequency is the one its response is
    corrected for.
    """

    device_type = "power_meter"
    keeps_settings = False
    MODEL: ClassVar[str] = ""  # as *IDN? names it

    quantities = U2000_QUANTITIES
    actions = POWER_SENSOR_ACTIONS

    @staticmethod
    def connection(resource: str, timeout: float = TIMEOUT) -> ConnectionSpec:
        """resource: USB0::<vendor>::<product>::<serial>::0::INSTR or a VISA alias."""
        return ConnectionSpec(VISA, resource=resource, timeout=timeout)

    @classmethod
    def recommended_connection(cls) -> Dict[str, Any]:
        """Its resource is the bench's own: Setup asks for it."""
        return recommendation(VISA, timeout=TIMEOUT)

    def test(self) -> bool:
        return self.MODEL in self.identify()

    def reset(self) -> None:
        self.write("*RST")

    def read_power(self) -> float:
        return self.query_float(READ_DBM)

    # The frequency its response is corrected for
    def set_frequency(self, frequency: float) -> None:
        """Hz"""
        self.write(f"SENS:FREQ {frequency}")

    def get_frequency(self) -> float:
        return self.query_float("SENS:FREQ?")

    def read_temperature(self) -> float:
        """K, of the sensor"""
        return celsius_to_kelvin(self.query_float("SENS:TEMP?"))

    # Averaging filter
    def set_averaging(self, value: bool) -> None:
        self.write(f"SENS:AVER:STAT {1 if value else 0}")

    def get_averaging(self) -> bool:
        return self.query_bool("SENS:AVER:STAT?")

    def set_averaging_auto(self, value: bool) -> None:
        """On: the sensor chooses the count by the power and turns averaging on."""
        self.write(f"SENS:AVER:COUN:AUTO {1 if value else 0}")

    def get_averaging_auto(self) -> bool:
        return self.query_bool("SENS:AVER:COUN:AUTO?")

    def set_averaging_count(self, count: int) -> None:
        """Readings averaged; the sensor turns auto averaging off, averaging on."""
        self.write(f"SENS:AVER:COUN {int(count)}")

    def get_averaging_count(self) -> int:
        return self.query_int("SENS:AVER:COUN?")

    def set_measurement_rate(self, rate: str) -> None:
        if rate not in MEASUREMENT_RATES:
            raise ConfigurationError(
                f"{self.name}: measurement rate {rate!r} is not one of {MEASUREMENT_RATES}"
            )
        self.write(f"SENS:MRAT {rate}")

    def get_measurement_rate(self) -> str:
        rate = self.query("SENS:MRAT?").upper()
        if rate not in MEASUREMENT_RATES:
            raise ConfigurationError(f"{self.name}: unknown measurement rate {rate!r}")
        return rate

    # Offset of the setup (an attenuator, a cable), added to every reading
    def set_offset(self, db: float) -> None:
        """dB; the sensor turns the offset on with it."""
        self.write(f"SENS:CORR:GAIN2 {db}")

    def get_offset(self) -> float:
        """dB, 0 while the offset is off."""
        if not self.query_bool("SENS:CORR:GAIN2:STAT?"):
            return 0.0
        return self.query_float("SENS:CORR:GAIN2?")

    # Zeroing
    def zero(self) -> None:
        """Internal zero: the signal at the input may stay on."""
        self._zero("INT")

    def zero_external(self) -> None:
        """Zero of what the input sees: the signal must be off."""
        self._zero("EXT")

    def _zero(self, kind: str) -> None:
        with self.transport.transaction():
            self.write("*CLS")  # what the queue holds after it is the zero's
            self.write(f"CAL:ZERO:TYPE {kind}")
            self.write("CAL:ZERO:AUTO ONCE")
            self.query("*OPC?")  # answers once the zero is done
            failed = self.errors()
        if failed:
            raise InstrumentError(f"{self.name}: zeroing failed: {'; '.join(failed)}")


class KeysightU2002H(KeysightU2000):
    """U2002H: 50 MHz – 24 GHz, −50…+30 dBm, at most +33 dBm at its input."""

    driver_key = "keysight.u2002h"
    MODEL = "U2002H"
    limits = {CORRECTION_FREQUENCY.key: Limit(minimum=50e6, maximum=24e9)}
