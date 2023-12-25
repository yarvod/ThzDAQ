from typing import List, Literal

import settings
from utils.classes import BaseInstrument


class PowerSupplyDP832A(BaseInstrument):
    model = "DP832A"
    """
    Default port 5555
    Default host 169.254.0.14
    """

    def __init__(
        self,
        host: str = "169.254.0.14",
        gpib: int = None,
        adapter: str = settings.SOCKET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")

    def test(self) -> bool:
        result = self.query("*TST?")
        return "TopBoard:PASS,BottomBoard:PASS,Fan:PASS" in result

    def set_current(self, channel: int, current: float):
        self.write(f":SOURce{channel}:CURRent {current}")

    def get_current(self, channel: int) -> float:
        return float(self.query(f":SOURce{channel}:CURRent?"))

    def set_voltage(self, channel: int, voltage: float):
        self.write(f":SOURce{channel}:VOLTage {voltage}")

    def get_voltage(self, channel: int) -> float:
        return float(self.query(f":SOURce{channel}:VOLTage?"))

    def measure_all(self, channel: int) -> List[float]:
        """
        :param channel: channel id
        :return: List of voltage, current, power values
        """
        response = self.query(f":MEAS:ALL? CH{channel}")
        return [float(i) for i in response.split(",")]

    def measure_current(self, channel: int) -> float:
        return float(self.query(f":MEAS:CURR? CH{channel}"))

    def measure_voltage(self, channel: int) -> float:
        return float(self.query(f":MEAS:VOLTage? CH{channel}"))

    def measure_power(self, channel: int) -> float:
        return float(self.query(f":MEAS:POWEr? CH{channel}"))

    def set_output(self, channel: int, output: Literal["ON", "OFF"] = "OFF"):
        self.write(f":OUTP CH{channel},{output}")

    def get_output(self, channel: int) -> str:
        """
        :param channel: channel number
        :return: OFF or ON
        """
        return self.query(f":OUTP? CH{channel}")


if __name__ == "__main__":
    d = PowerSupplyDP832A(host="169.254.0.14", port=5555)
    print(d.idn())
    print(d.get_output(1))
