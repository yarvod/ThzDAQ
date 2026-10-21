from typing import Literal, Optional

from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply
from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec, Transport
from thzdaq_instruments.units import watt_to_dbm


class RohdeSchwarzHMP2030(ScpiPowerSupply):
    """R&S HMP2030, three channels, LAN port 5025.

    Commands act on the selected channel, so selection and command run in one
    transaction. Channel outputs take effect only with the general output on.
    """

    channel_keys = (1, 2, 3)

    @staticmethod
    def connection(host: str = "169.254.0.30", port: int = 5025) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return self.query("*TST?") == "0"

    def _select(self, channel: int) -> None:
        # The legacy driver sent "INSTrument:NSELest", which is not a valid SCPI header
        self.write(f"INST:NSEL {channel}")

    def _write_on(self, channel: int, command: str) -> None:
        with self.transport.transaction():
            self._select(channel)
            self.write(command)

    def _float_on(self, channel: int, command: str) -> float:
        with self.transport.transaction():
            self._select(channel)
            return self.query_float(command)

    def set_general_output(self, value: bool) -> None:
        self.write(f"OUTP:GEN {1 if value else 0}")

    def get_general_output(self) -> bool:
        return self.query_bool("OUTP:GEN?")

    def _set_output(self, channel: int, value: bool) -> None:
        self._write_on(channel, f"OUTP:STAT {1 if value else 0}")

    def _get_output(self, channel: int) -> bool:
        with self.transport.transaction():
            self._select(channel)
            return self.query_bool("OUTP:STAT?")

    def _set_voltage(self, channel: int, voltage: float) -> None:
        self._write_on(channel, f"SOUR:VOLT:LEV:AMPL {voltage}")

    def _get_voltage(self, channel: int) -> float:
        return self._float_on(channel, "SOUR:VOLT:LEV:AMPL?")

    def _set_current(self, channel: int, current: float) -> None:
        self._write_on(channel, f"SOUR:CURR:LEV:AMPL {current}")

    def _get_current(self, channel: int) -> float:
        return self._float_on(channel, "SOUR:CURR:LEV:AMPL?")

    def _measure(self, channel: int) -> ChannelReading:
        with self.transport.transaction():
            self._select(channel)
            return ChannelReading(
                self.query_float("MEAS:SCAL:VOLT?"), self.query_float("MEAS:SCAL:CURR?")
            )


PowerUnit = Literal["DBM", "W", "DBUV"]
# dBµV -> dBm on a 50 Ohm system
DBUV_TO_DBM = -107.0


class RohdeSchwarzNRX(ScpiInstrument):
    """R&S NRX power meter, sensor 1, LAN port 5025.

    read_power() always returns dBm whatever display unit is selected.
    """

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

    def set_aperture_time(self, seconds: float) -> None:
        self.write(f"CALC:APER {seconds}")

    def set_filter_time(self, seconds: float) -> None:
        self.write(f"CALC:CHAN:AVER:COUN:AUTO:MTIM {seconds}")

    def set_limits(self, lower: float, upper: float) -> None:
        self.write(f"CALC1:LIM1:LOW:DATA {lower}")
        self.write(f"CALC1:LIM1:UPP:DATA {upper}")

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
