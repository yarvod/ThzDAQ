from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec


class RigolDP832A(ScpiPowerSupply):
    """Rigol DP832A, three channels, LAN port 5555."""

    channel_keys = (1, 2, 3)

    @staticmethod
    def connection(host: str = "169.254.0.14", port: int = 5555) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return "TopBoard:PASS,BottomBoard:PASS,Fan:PASS" in self.query("*TST?")

    def _set_output(self, channel: int, value: bool) -> None:
        self.write(f":OUTP CH{channel},{'ON' if value else 'OFF'}")

    def _get_output(self, channel: int) -> bool:
        return self.query_bool(f":OUTP? CH{channel}")

    def _set_voltage(self, channel: int, voltage: float) -> None:
        self.write(f":SOURce{channel}:VOLTage {voltage}")

    def _get_voltage(self, channel: int) -> float:
        return self.query_float(f":SOURce{channel}:VOLTage?")

    def _set_current(self, channel: int, current: float) -> None:
        self.write(f":SOURce{channel}:CURRent {current}")

    def _get_current(self, channel: int) -> float:
        return self.query_float(f":SOURce{channel}:CURRent?")

    def _measure(self, channel: int) -> ChannelReading:
        command = f":MEAS:ALL? CH{channel}"
        response = self.query(command)
        try:
            voltage, current, _power = (float(v) for v in response.split(","))
        except ValueError as e:
            raise InstrumentResponseError(
                f"{self.name}: unexpected answer {response!r} to {command!r}"
            ) from e
        return ChannelReading(voltage, current)
