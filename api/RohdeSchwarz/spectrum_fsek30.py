from typing import List, Tuple

import numpy as np

import settings
from utils.classes import BaseInstrument


class SpectrumBlock(BaseInstrument):
    def __init__(
        self,
        host: str,
        gpib: int = None,
        adapter: str = settings.PROLOGIX_ETHERNET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self) -> str:
        return self.query("*IDN?")

    def reset(self) -> None:
        self.write("*RST")

    def test(self) -> bool:
        response = self.idn()
        if not response or "Rohde" not in response:
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

    def get_trace_data(self, start, stop) -> Tuple[List[float], List[float]]:
        response = self.query(":TRAC:DATA? TRACE1", delay=0)
        points_raw = response.split(",")
        frequency_list = np.linspace(start, stop, len(points_raw))
        frequency_indxs = []
        points = []
        for i, p in enumerate(points_raw):
            try:
                points.append(float(p))
                frequency_indxs.append(i)
            except ValueError:
                continue
        return points, frequency_list[frequency_indxs]

    def set_video_bw(self, value: float):
        """Available values, kHz"""
        available_list = np.array(
            [
                1e-3,
                2e-3,
                3e-3,
                5e-3,
                1e-2,
                2e-2,
                3e-2,
                5e-2,
                1e-1,
                2e-1,
                3e-1,
                5e-1,
                1,
                2,
                3,
                5,
                10,
                20,
                30,
                50,
                1e2,
                2e2,
                3e2,
                5e2,
                1e3,
                2e3,
                5e3,
                10e3,
            ]
        )
        diff = np.abs(available_list - value)
        min_ind = np.where(diff == np.min(diff))[0][0]
        bw = available_list[min_ind]
        self.write(f":BWIDth:VIDeo {bw}kHz")

    def set_video_bw_auto(self, value: bool):
        """True - ON, False - OFF"""
        if value:
            return self.query(f":BWIDth:VIDeo:AUTO ON")
        return self.query(f":BWIDth:VIDeo:AUTO OFF")

    def set_start_frequency(self, value: float):
        """value in Hz"""
        self.write(f":FREQuency:STARt {value}Hz")

    def get_start_frequency(self):
        """value in Hz"""
        return float(self.query(f":FREQuency:STARt?"))

    def set_stop_frequency(self, value: float):
        """value in Hz"""
        self.write(f":FREQuency:STOP {value}Hz")

    def get_stop_frequency(self):
        """value in Hz"""
        return float(self.query(f":FREQuency:STOP?"))


if __name__ == "__main__":
    # block = SpectrumBlock(
    #     host="169.254.156.103", gpib=21, adapter=settings.PROLOGIX_ETHERNET, port=1234
    # )
    block = SpectrumBlock(
        host="169.254.75.176", gpib=None, adapter=settings.SOCKET, port=5025, delay=0
    )
    print(block.idn())
    print(block.test())
    # print("freq", block.get_start_frequency())
