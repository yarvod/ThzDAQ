from typing import List

from api.adapters.prologix_ethernet_adapter import PrologixEthernetAdapter
from settings import PROLOGIX_ETHERNET
from store.state import state
from utils.classes import BaseInstrument
from utils.decorators import exception


class SpectrumBlock(BaseInstrument):
    def __init__(
        self,
        host: str = state.PROLOGIX_IP,
        gpib: int = None,
        adapter: str = PROLOGIX_ETHERNET,
        *args,
        **kwargs,
    ):
        self.adapter = PrologixEthernetAdapter(host=host)
        super().__init__(host, gpib, adapter, *args, **kwargs)

    @exception
    def idn(self) -> str:
        return self.query("*IDN?")

    @exception
    def reset(self) -> None:
        self.write("*RST")

    def tst(self) -> bool:
        response = self.idn()
        if not response or "FSEK" not in response:
            return False
        return True

    @exception
    def test(self):
        """Test function: 0 - Good, 1 - Bad"""
        return self.query("*TST?")

    def peak_search(self) -> None:
        self.write(f"CALC:MARK:MAX")

    @exception
    def get_peak_freq(self) -> float:
        return float(self.query(f"CALC:MARK:X?"))

    @exception
    def get_peak_power(self) -> float:
        return float(self.query(f"CALC:MARK:Y?"))

    @exception
    def get_trace_data(self) -> List[float]:
        response = self.query(f":TRAC:DATA? TRACE1")
        return [float(i) for i in response.split(",")]


if __name__ == "__main__":
    block = SpectrumBlock()
    print("idn", block.idn())
    print("trace", block.get_trace_data())
