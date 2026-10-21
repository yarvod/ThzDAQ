from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec


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
