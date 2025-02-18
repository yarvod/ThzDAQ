from typing import Literal

import settings
from utils.classes import BaseInstrument


class Multimeter(BaseInstrument):
    """
    Functions:
    - F0 = DC volts
    - F1 = AC volts
    - F2 = Ohms
    - F3 = DC current
    - F4 = AC current
    - F5 = ACV dB
    - F6 = ACA dB

    Ranges:
    |Range| DCV       | ACV       | DCA       | ACA       | Ohms      | ACV dB    | ACA dB    |
    |-----|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
    | RO  | Auto      | Auto      | Auto      | Auto      | Auto      | Auto      | Auto      |
    | R1  | 30mV      | 30mV      | 3OmA      | 3OmA      | 300 Ohm   | Auto      | Auto      |
    | R2  | 3V        | 3V        | 3A        | 3A        | 3k Ohm    | Auto      | Auto      |
    | R3  | 30V       | 30V       | 3A        | 3A        | 30k Ohm   | Auto      | Auto      |
    | R4  | 300V      | 300V      | 3A        | 3A        | 300k Ohm  | Auto      | Auto      |
    | R5  | 300V      | 300V      | 3A        | 3A        | 3M Ohm    | Auto      | Auto      |
    | R6  | 300V      | 300V      | 3A        | 3A        | 30M Ohm   | Auto      | Auto      |
    | R7  | 300V      | 300V      | 3A        | 3A        | 300M Ohm  | Auto      | Auto      |
    """

    model = "199"

    def __init__(
        self,
        host: str = "169.254.156.103",
        gpib: int = 26,
        adapter: str = settings.PROLOGIX_ETHERNET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")

    def tst(self):
        return self.query("*TST?")

    def test(self) -> bool:
        res = self.idn()
        return "NDCV" in res

    def set_range(self, value: Literal["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7"]):
        self.write(f"{value}X")

    def set_function(self, value: Literal["F0", "F1", "F2", "F3", "F4", "F5", "F6"]):
        self.write(f"{value}X")

    def get_voltage(self):
        res = self.idn()
        return float(res.replace("NDCV", ""))


if __name__ == "__main__":
    m = Multimeter(gpib=26)
    print(m.idn())
    print(m.tst())
    print(m.get_voltage())
