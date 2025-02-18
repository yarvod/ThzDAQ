from typing import Dict, Literal

from settings import SOCKET
from utils.classes import BaseInstrument


class TemperatureController(BaseInstrument):
    """
    Default port 7777
    Default host 169.254.0.56
    """

    def __init__(
        self,
        host: str = "169.254.0.56",
        gpib: int = None,
        adapter: str = SOCKET,
        delay=0,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, delay=delay, **kwargs)

    def idn(self) -> str:
        return self.query("*IDN?")

    def test(self) -> bool:
        result = self.idn()
        return "LSCI,MODEL336,LSA2CMQ/LSA2C8R,2.9" in result

    def get_mode(self) -> str:
        """0 = local, 1 = remote, 2 = remote with local lockout."""
        return self.query("MODE?")

    def set_mode(self, value: int):
        """0 = local, 1 = remote, 2 = remote with local lockout."""
        self.write(f"MODE {value}")

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

    def get_out_mode(self, output: Literal[1, 2, 3, 4] = 1):
        res = self.query(f"OUTMODE? {output}")
        mode, input_, powerup_enable = res.split(",")
        return {
            "mode": int(mode),
            "input": int(input_),
            "powerup_enable": int(powerup_enable),
        }

    def set_out_mode(
        self,
        output: Literal[1, 2, 3, 4] = 1,
        mode: Literal[0, 1, 2, 3, 4, 5] = 1,
        input_: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8] = 1,
        powerup_enable: Literal[0, 1] = 1,
    ):
        """
        mode:
        0 = Off, 1 = Closed Loop PID, 2 = Zone, 3 = Open Loop, 4 = Monitor Out, 5 = Warmup Supply

        output: 1–4

        input_:
        0 = None, 1 = A, 2 = B, 3 = C, 4 = D (5 = Input D2, 6 = Input D3, 7 = Input D4, 8 = Input D5 for 3062 option)

        powerup_enable:
        0 = powerup enable off, 1 = powerup enable on
        """


if __name__ == "__main__":
    tc = TemperatureController(
        host="169.254.156.101", port=1234, adapter="PROLOGIX ETHERNET"
    )
    print(tc.get_out_mode())
