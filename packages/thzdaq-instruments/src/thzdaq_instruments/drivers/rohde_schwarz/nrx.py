from typing import Literal, Optional

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.quantities import POWER_METER_QUANTITIES
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec, Transport
from thzdaq_instruments.units import watt_to_dbm

PowerUnit = Literal["DBM", "W", "DBUV"]
# dBµV -> dBm on a 50 Ohm system
DBUV_TO_DBM = -107.0


class RohdeSchwarzNRX(ScpiInstrument):
    """R&S NRX power meter, sensor 1, LAN port 5025.

    read_power() always returns dBm whatever display unit is selected.
    """

    quantities = POWER_METER_QUANTITIES

    def __init__(
        self,
        transport: Transport,
        *,
        name: Optional[str] = None,
        aperture_time: Optional[float] = None,
        averaging: Optional[bool] = None,
    ):
        super().__init__(transport, name=name)
        self._unit: Optional[PowerUnit] = None
        if averaging is not None:
            self.set_averaging(averaging)
        if aperture_time is not None:
            self.set_aperture_time(aperture_time)

    @staticmethod
    def connection(host: str = "169.254.2.20", port: int = 5025) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return self.query("*TST?") == "0"

    def reset(self) -> None:
        self.write("*RST")
        self._unit = None

    def set_averaging(self, value: bool) -> None:
        self.write(f"CALC:CHAN:AVER:STAT {1 if value else 0}")

    def get_averaging(self) -> bool:
        return self.query_bool("CALC:CHAN:AVER:STAT?")

    def set_aperture_time(self, seconds: float) -> None:
        self.write(f"CALC:APER {seconds}")

    def get_aperture_time(self) -> float:
        return self.query_float("CALC:APER?")

    def set_filter_time(self, seconds: float) -> None:
        self.write(f"CALC:CHAN:AVER:COUN:AUTO:MTIM {seconds}")

    def get_filter_time(self) -> float:
        return self.query_float("CALC:CHAN:AVER:COUN:AUTO:MTIM?")

    def set_lower_limit(self, value: float) -> None:
        """In the display unit."""
        self.write(f"CALC1:LIM1:LOW:DATA {value}")

    def get_lower_limit(self) -> float:
        return self.query_float("CALC1:LIM1:LOW:DATA?")

    def set_upper_limit(self, value: float) -> None:
        """In the display unit."""
        self.write(f"CALC1:LIM1:UPP:DATA {value}")

    def get_upper_limit(self) -> float:
        return self.query_float("CALC1:LIM1:UPP:DATA?")

    def set_limits(self, lower: float, upper: float) -> None:
        self.set_lower_limit(lower)
        self.set_upper_limit(upper)

    def set_units(self, unit: PowerUnit) -> None:
        if unit not in ("DBM", "W", "DBUV"):
            raise ConfigurationError(f"Unsupported power unit {unit!r}")
        self.write(f"UNIT1:POW {unit}")
        self._unit = unit

    def get_units(self) -> PowerUnit:
        unit = self.query("UNIT1:POW?").upper()
        if unit not in ("DBM", "W", "DBUV"):
            raise ConfigurationError(f"{self.name}: unsupported power unit {unit!r}")
        self._unit = unit
        return unit

    def read(self) -> float:
        """New measurement in the display unit."""
        return self.query_float("READ?")

    def fetch(self) -> float:
        """Last measurement in the display unit, without triggering."""
        return self.query_float("FETCH?")

    def read_power(self) -> float:
        unit = self._unit or self.get_units()
        value = self.read()
        if unit == "W":
            return watt_to_dbm(value)
        if unit == "DBUV":
            return value + DBUV_TO_DBM
        return value
