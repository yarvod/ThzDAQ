from typing import List

from settings import PROLOGIX_ETHERNET
from utils.classes import BaseInstrument
from utils.decorators import exception


class SpectrumBlock(BaseInstrument):
    def __init__(
        self,
        host: str,
        gpib: int = None,
        adapter: str = PROLOGIX_ETHERNET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    @exception
    def idn(self) -> str:
        return self.query("*IDN?")

    @exception
    def reset(self) -> None:
        self.write("*RST")

    def test(self) -> bool:
        response = self.idn()
        if not response or "FSEK" not in response:
            return False
        return True

    def tst(self):
        """Test function: 0 - Good, 1 - Bad"""
        return self.query("*TST?")

    def peak_search(self) -> None:
        self.write(f"CALC:MARK:MAX")

    def get_peak_freq(self) -> float:
        return float(self.query(f"CALC:MARK:X?"))

    def get_peak_power(self) -> float:
        return float(self.query(f"CALC:MARK:Y?"))

    def get_trace_data(self) -> List[float]:
        response = self.query(f":TRAC:DATA? TRACE1")
        points = []
        for p in response.split(","):
            try:
                points.append(float(p))
            except ValueError:
                continue
        return points


if __name__ == "__main__":
    block = SpectrumBlock()
    print("idn", block.idn())
    print("trace", block.get_trace_data())
