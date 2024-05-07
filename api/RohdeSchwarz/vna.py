import logging
import time
from typing import Dict

import numpy as np

from settings import SOCKET
from store.state import state

from utils.classes import BaseInstrument


logger = logging.getLogger(__name__)


class VNABlock(BaseInstrument):
    """
    Default host 169.254.106.189
    Default port 5025
    """

    def __init__(
        self,
        host: str = "169.254.106.189",
        gpib: int = None,
        adapter: str = SOCKET,
        port: int = 5025,
        *args,
        **kwargs,
    ):
        kwargs["port"] = port
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self) -> str:
        return self.query("*IDN?")

    def test(self) -> bool:
        """
        Methods for self testing Instrument.
        Error - 1
        Ok - 0
        """
        result = self.idn()
        return "Rohde&Schwarz,ZVA67-4Port" in result

    def set_sweep(self, points: int = state.VNA_POINTS) -> None:
        self.write(f"SWE:POIN {points}")

    def get_sweep(self) -> int:
        return int(self.query(f"SWE:POIN?", delay=0.05))

    def set_channel_format(self, form: str = state.VNA_CHANNEL_FORMAT) -> None:
        self.write(f"CALC:FORM {form}")

    def get_channel_format(self):
        return self.query("CALC:FORM?", delay=0.05)

    def set_power(self, power: float = state.VNA_POWER) -> None:
        self.write(f"SOUR:POW {power}")

    def get_power(self):
        return self.query("SOUR:POW?", delay=0.05)

    def get_start_frequency(self) -> float:
        return float(self.query("SENS:FREQ:STAR?", delay=0.05))

    def get_stop_frequency(self) -> float:
        return float(self.query("SENS:FREQ:STOP?", delay=0.05))

    def set_start_frequency(self, freq: float) -> None:
        self.write(f"SENS:FREQ:STAR {freq}")

    def set_stop_frequency(self, freq: float) -> None:
        self.write(f"SENS:FREQ:STOP {freq}")

    def set_parameter(
        self, parameter: str = "S11", trace: str = "Trc1", channel: int = 1
    ) -> None:
        self.write(f"CALCulate{channel}:PARameter:DEFine {trace},{parameter}")

    def get_parameter_catalog(self, channel: int = 1) -> Dict[str, str]:
        """Current catalog of parameters
        :returns
        Dict of Trace and Parameter map {"Trc1": "S11"}
        """
        response = self.query(f"CALCulate{channel}:PARameter:CATalog?", delay=0.05)
        response = response.replace("'", "")
        lst = response.split(",")
        lst_traces = [_ for _ in lst[::2]]
        lst_params = [_ for _ in lst[1::2]]
        return dict(zip(lst_traces, lst_params))

    def get_data(self) -> Dict:
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
                logger.error(f"[{self.__class__.__name__}.get_data] Value error!")
                continue
            if np.sum(np.abs(resp)) > 0:
                real = resp[::2]
                imag = resp[1::2]
                freq = list(
                    np.linspace(
                        self.get_start_frequency(),
                        self.get_stop_frequency(),
                        self.get_sweep(),
                    )
                )
                s_param = self.get_parameter_catalog()["Trc1"]
                power = self.get_power()

                return {
                    "array": np.array([r + i * 1j for r, i in zip(real, imag)]),
                    "real": real,
                    "imag": imag,
                    "freq": freq,
                    "parameter": s_param,
                    "power": power,
                }
        return {}


if __name__ == "__main__":
    vna = VNABlock(start=2e9, stop=16e9, points=1001, delay=0.4)
    print(vna.get_parameter_catalog())
    print(vna.get_data())
    # refl = vna.get_data()
    # freq = np.linspace(2e9, 16e9, 1001).tolist()
    # data = {"real": list(refl.real), "imag": list(refl.imag), "freq": freq}
    # with open("s12.json", "w", encoding="utf-8") as file:
    #     json.dump(data, file, ensure_ascii=False, indent=4)
