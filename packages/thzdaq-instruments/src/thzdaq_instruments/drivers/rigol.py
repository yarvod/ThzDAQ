from typing import Optional

from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply, SupplyChannel
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import CURRENT_SET, VOLTAGE_SET
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec


class RigolChannel(SupplyChannel):
    """An output of the DP832A: it also has over-voltage and over-current
    protection (OutputProtection)."""

    instrument: "RigolDP832A"

    def set_protection(
        self, voltage: Optional[float], current: Optional[float]
    ) -> None:
        self.instrument._set_protection(self.key, voltage, current)


class RigolDP832A(ScpiPowerSupply):
    """Rigol DP832A, three channels, LAN port 5555."""

    driver_key = "rigol.dp832a"
    device_type = "power_supply"

    channel_class = RigolChannel
    channel_keys = (1, 2, 3)
    # Rated outputs: CH1 and CH2 30 V / 3 A, CH3 5 V / 3 A
    limits = {VOLTAGE_SET.key: Limit(0.0, 30.0), CURRENT_SET.key: Limit(0.0, 3.0)}
    channel_limits = {
        3: {VOLTAGE_SET.key: Limit(0.0, 5.0), CURRENT_SET.key: Limit(0.0, 3.0)}
    }

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

    def _set_protection(
        self, channel: int, voltage: Optional[float], current: Optional[float]
    ) -> None:
        if voltage is not None:
            self.write(f":OUTP:OVP:VAL CH{channel},{voltage}")
            self.write(f":OUTP:OVP CH{channel},ON")
        if current is not None:
            self.write(f":OUTP:OCP:VAL CH{channel},{current}")
            self.write(f":OUTP:OCP CH{channel},ON")

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
