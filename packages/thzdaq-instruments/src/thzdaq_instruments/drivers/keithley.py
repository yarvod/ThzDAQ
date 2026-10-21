from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import PROLOGIX, ConnectionSpec


class Keithley2200(ScpiPowerSupply):
    """Keithley 2200-30-5, single channel, usually GPIB behind Prologix."""

    channel_keys = (1,)

    @staticmethod
    def connection(host: str = "169.254.156.103", gpib: int = 22) -> ConnectionSpec:
        return ConnectionSpec(PROLOGIX, host=host, gpib=gpib)

    def test(self) -> bool:
        return self.query("*TST?") == "0"

    def _set_output(self, channel: int, value: bool) -> None:
        self.write(f"OUTPUT {1 if value else 0}")

    def _get_output(self, channel: int) -> bool:
        return self.query_bool("OUTPUT?")

    def _set_voltage(self, channel: int, voltage: float) -> None:
        self.write(f"SOUR:VOLT {voltage}V")

    def _get_voltage(self, channel: int) -> float:
        return self.query_float("SOUR:VOLT?")

    def _set_current(self, channel: int, current: float) -> None:
        self.write(f"SOUR:CURR {current}A")

    def _get_current(self, channel: int) -> float:
        return self.query_float("SOUR:CURR?")

    def _measure(self, channel: int) -> ChannelReading:
        with self.transport.transaction():
            return ChannelReading(
                self.query_float("MEAS:VOLT?"), self.query_float("MEAS:CURR?")
            )
