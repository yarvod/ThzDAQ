import settings
from store.state import state
from utils.classes import BaseInstrument


class PowerSupply(BaseInstrument):
    def __init__(
        self,
        host: str = state.PROLOGIX_IP,
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
        return float(self.query("MEAS:CURR?"))

    def get_set_current(self):
        return float(self.query("SOUR:CURR?"))

    def get_voltage(self):
        return float(self.query("MEAS:VOLT?"))

    def get_set_voltage(self):
        return float(self.query("SOUR:VOLT?"))

    def set_current(self, current: float) -> float:
        self.write(f"SOUR:CURR {current}A")
        return float(self.query(f"SOUR:CURR?"))

    def set_voltage(self, voltage: float) -> float:
        self.write(f"SOUR:VOLT {voltage}V")
        return float(self.query(f"SOUR:VOLT?"))


if __name__ == "__main__":
    block = PowerSupply()
    print(block.test())
    print(block.get_set_voltage())
