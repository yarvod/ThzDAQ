from typing import Dict

from api.adapters.socket_adapter import SocketAdapter
from settings import SOCKET
from store.state import state
from utils.classes import BaseInstrument


class TemperatureController(BaseInstrument):
    def __init__(
        self,
        host: str = state.LAKE_SHORE_IP,
        gpib: int = None,
        adapter: str = SOCKET,
        delay=0,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)
        self.adapter = SocketAdapter(host=host, port=kwargs.get("port"), delay=delay)

    def idn(self) -> str:
        return self.query("*IDN?")

    def test(self) -> str:
        result = self.idn()
        if "LSCI,MODEL336,LSA2CMQ/LSA2C8R,2.9" in result:
            return "OK"
        return "ERROR"

    def get_temperature_a(self) -> float:
        return float(self.query("KRDG? A"))

    def get_temperature_c(self) -> float:
        return float(self.query("KRDG? C"))

    def get_temperature_b(self) -> float:
        return float(self.query("KRDG? B"))

    def get_heater_output(self, output: int = 1):
        """Heater output in percent (%)"""
        return self.query(f"HTR? {output}")

    def get_heater_setup(self, output: int = 1) -> Dict:
        response = self.query(f"HTRSET? {output}")
        response_lst = response.split(",")
        return {
            "resistance": int(response_lst[0]),  # 1 = 25 Ohm, 2 = 50 Ohm
            "max_current": int(
                response_lst[1]
            ),  # 0 = User Specified, 1 = 0.707 A, 2 = 1 A, 3 = 1.141 A, 4 = 2 A
            "max_user_current": float(response_lst[2]),
            "current/power": int(response_lst[3]),  # 1 = current, 2 = power
        }

    def heater_setup(
        self,
        output: int = 1,  # 1 = Heater 1, 2 = Heater 2
        resistance: int = 1,  # 1 = 25 Ohm, 2 = 50 Ohm
        max_current: int = 1,  # 0 = User Specified, 1 = 0.707 A, 2 = 1 A, 3 = 1.141 A, 4 = 2 A
        max_user_current: float = 0,
        current_power: int = 1,  # 1 = current, 2 = power
    ) -> None:
        self.write(
            f"HTRSET {output},{resistance},{max_current},{max_user_current},{current_power}"
        )

    def get_heater_status(self, output: int = 1) -> int:
        """0 = no error, 1 = heater open load, 2 = heater short"""
        return int(self.query(f"HTRST? {output}"))

    def get_heater_range(self, output: int = 1) -> int:
        """0 = Off, 1 = Low, 2 = Medium, 3 = High"""
        return int(self.query(f"RANGE? {output}"))

    def set_heater_range(self, output: int = 1, value: int = 1) -> None:
        """0 = Off, 1 = Low, 2 = Medium, 3 = High"""
        self.write(f"RANGE {output},{value}")

    def get_control_point(self, output: int = 1) -> float:
        return float(self.query(f"SETP? {output}"))

    def set_control_point(self, value: float, output: int = 1) -> None:
        self.write(f"SETP {output},{value}")

    def get_manual_output(self, output: int = 1) -> float:
        return float(self.query(f"MOUT? {output}"))

    def set_manual_output(self, value: float, output: int = 1) -> None:
        self.write(f"MOUT {output},{value}")


if __name__ == "__main__":
    tc = TemperatureController(port=state.LAKE_SHORE_PORT)
    print(tc.get_heater_output())
    print(tc.get_manual_output())
