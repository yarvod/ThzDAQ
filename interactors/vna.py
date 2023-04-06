import time

import numpy as np

from config import VNA_ADDRESS, VNA_SPARAM, VNA_POINTS, VNA_POWER, VNA_CHANNEL_FORMAT

from RsInstrument import *

from utils.classes import Singleton


class Instrument(RsInstrument, metaclass=Singleton):
    ...


class VNABlock(metaclass=Singleton):
    def __init__(
        self,
        vna_ip: str = VNA_ADDRESS,
        points: int = VNA_POINTS,
        channel_format: str = VNA_CHANNEL_FORMAT,
        power: float = VNA_POWER,
        param: str = VNA_SPARAM,
    ):
        self.vna_ip = vna_ip
        self.param = param
        self.update(vna_ip, points, channel_format, power, param)

    def update(
        self,
        vna_ip: str = VNA_ADDRESS,
        points: int = VNA_POINTS,
        channel_format: str = VNA_CHANNEL_FORMAT,
        power: float = VNA_POWER,
        param: str = VNA_SPARAM,
    ):
        self.vna_ip = vna_ip
        self.param = param
        self.set_sweep(points)
        self.set_channel_format(channel_format)
        self.set_power(power)

    @property
    def instr(self):
        return Instrument(f"TCPIP::{self.vna_ip}::INSTR", id_query=True, reset=False)

    def name(self):
        return self.instr.query_str("*IDN?")

    def test(self) -> str:
        """
        Methods for self testing Instrument.
        Error - 1
        Ok - 0
        """
        return self.instr.query_str("*TST?")

    def set_sweep(self, points: int = VNA_POINTS):
        self.instr.write_int("SWE:POIN", points)

    def set_channel_format(self, form: str = VNA_CHANNEL_FORMAT):
        self.instr.write(f"CALC:FORM {form}")

    def get_channel_format(self):
        return self.instr.query_str("CALC:FORM?")

    def set_power(self, power: float = VNA_POWER):
        self.instr.write(f"SOUR:POW {power}")

    def get_power(self):
        return self.instr.query_str("SOUR:POW?")

    def get_start_frequency(self):
        return self.instr.query_str("SENS:FREQ:STAR?")

    def get_stop_frequency(self):
        return self.instr.query_str("SENS:FREQ:STOP?")

    def set_start_frequency(self, freq: float):
        self.instr.write_float("SENS:FREQ:STAR", freq)

    def set_stop_frequency(self, freq: float):
        self.instr.write_float("SENS:FREQ:STOP", freq)

    def get_reflection(self) -> np.ndarray[complex]:
        """
        Method to get reflection level from VNA
        """
        attempts = 5
        attempt = 0
        while attempt < attempts:
            time.sleep(0.05)
            attempt += 1
            resp = self.instr.query_bin_or_ascii_float_list("CALC:DATA? FDAT")
            if np.sum(np.abs(resp)) > 0:
                real = resp[::2]
                imag = resp[1::2]
                return np.array([r + i * 1j for r, i in zip(real, imag)])
        return np.array([])


if __name__ == "__main__":
    vna = VNABlock()
    print(vna.name())
    print(vna.set_start_frequency(2e9))
    print(vna.get_start_frequency())
    print(vna.set_stop_frequency(12e9))
    print(vna.get_stop_frequency())
    print(vna.get_reflection())
