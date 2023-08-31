import json
import logging
import time

import numpy as np

from settings import SOCKET
from store.state import state

from utils.classes import BaseInstrument
from utils.decorators import exception


logger = logging.getLogger(__name__)


class VNABlock(BaseInstrument):
    def __init__(
        self,
        host: str = state.VNA_ADDRESS,
        gpib: int = None,
        adapter: str = SOCKET,
        port: int = state.VNA_PORT,
        *args,
        **kwargs,
    ):
        kwargs["port"] = port
        super().__init__(host, gpib, adapter, *args, **kwargs)
        self.set_start_frequency(kwargs.get("start", state.VNA_FREQ_FROM))
        self.set_stop_frequency(kwargs.get("stop", state.VNA_FREQ_TO))
        self.set_sweep(kwargs.get("points", state.VNA_POINTS))
        self.set_power(kwargs.get("power", state.VNA_POWER))

    def idn(self) -> str:
        return self.query("*IDN?")

    @exception
    def test(self) -> str:
        """
        Methods for self testing Instrument.
        Error - 1
        Ok - 0
        """
        return self.query("*TST?")

    def set_sweep(self, points: int = state.VNA_POINTS) -> None:
        self.write(f"SWE:POIN {points}")

    def get_sweep(self) -> int:
        return int(self.query(f"SWE:POIN?"))

    def set_channel_format(self, form: str = state.VNA_CHANNEL_FORMAT) -> None:
        self.write(f"CALC:FORM {form}")

    def get_channel_format(self):
        return self.query("CALC:FORM?")

    def get_parameter_catalog(self, chan: int = 1) -> str:
        return self.query(f"CALCulate{chan}:PARameter:CATalog?")

    def set_power(self, power: float = state.VNA_POWER) -> None:
        self.write(f"SOUR:POW {power}")

    def get_power(self):
        return self.query("SOUR:POW?")

    def get_start_frequency(self) -> float:
        return float(self.query("SENS:FREQ:STAR?"))

    def get_stop_frequency(self) -> float:
        return float(self.query("SENS:FREQ:STOP?"))

    def set_start_frequency(self, freq: float) -> None:
        self.write(f"SENS:FREQ:STAR {freq}")

    def set_stop_frequency(self, freq: float) -> None:
        self.write(f"SENS:FREQ:STOP {freq}")

    def get_reflection(self) -> np.ndarray:
        """
        Method to get reflection level from VNA
        """
        attempts = 5
        attempt = 0
        while attempt < attempts:
            time.sleep(0.05)
            attempt += 1
            response = self.query("CALC:DATA? FDAT").split(",")
            try:
                resp = [float(i) for i in response]
            except ValueError:
                logger.error(f"[{self.__class__.__name__}.get_reflection] Value error!")
                continue
            if np.sum(np.abs(resp)) > 0:
                real = resp[::2]
                imag = resp[1::2]
                return np.array([r + i * 1j for r, i in zip(real, imag)])
        return np.array([])


if __name__ == "__main__":
    vna = VNABlock(start=2e9, stop=16e9, points=1001, delay=0.4)
    refl = vna.get_reflection()
    freq = np.linspace(2e9, 16e9, 1001).tolist()
    data = {"real": list(refl.real), "imag": list(refl.imag), "freq": freq}
    with open("s12.json", "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
