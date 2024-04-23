import settings
from utils.classes import BaseInstrument


class PowerSupply(BaseInstrument):
    model = "2200-30-5"

    def __init__(
        self,
        host: str = "169.254.156.103",
        gpib: int = 22,
        adapter: str = settings.PROLOGIX_ETHERNET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")

    def reset(self):
        self.write("*RST")

    def test(self) -> bool:
        """Test function: 0 - Good, 1 - Bad"""
        resp = self.query("*TST?").strip()
        return resp == "0"

    def set_output_state(self, value: int):
        """Output State 0 - off, 1 - on"""
        self.write(f"OUTPUT {value}")

    def get_output_state(self):
        """Output State 0 - off, 1 - on"""
        return self.query(f"OUTPUT?").strip()

    def get_current(self):
        response = self.query("MEAS:CURR?")
        try:
            return float(response)
        except ValueError:
            return None

    def get_sour_current(self):
        response = self.query("SOUR:CURR?")
        try:
            return float(response)
        except ValueError:
            return None

    def get_voltage(self):
        response = self.query("MEAS:VOLT?")
        try:
            return float(response)
        except ValueError:
            return None

    def get_sour_voltage(self):
        response = self.query("SOUR:VOLT?")
        try:
            return float(response)
        except ValueError:
            return None

    def set_current(self, current: float) -> None:
        self.write(f"SOUR:CURR {current}A")

    def set_voltage(self, voltage: float) -> None:
        self.write(f"SOUR:VOLT {voltage}V")


if __name__ == "__main__":
    block = PowerSupply()
    print(block.test())
    print(block.get_sour_voltage())
