from config import VNA_ADDRESS, VNA_SPARAM, VNA_POINTS

from RsInstrument import *

from utils.classes import Singleton


class Instrument(RsInstrument, metaclass=Singleton):
    ...


class VNABlock:
    def __init__(self, vna_ip: str = VNA_ADDRESS, param: str = VNA_SPARAM):
        self.vna_ip = vna_ip
        self.param = param
        self.set_sweep()
        self.set_channel_format()
        self.set_power()

    @property
    def instr(self):
        return Instrument(f"TCPIP::{VNA_ADDRESS}::INSTR", id_query=True, reset=False)

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

    def set_channel_format(self, form: str = "COMP"):
        self.instr.write(f"CALC:FORM {form}")

    def get_channel_format(self):
        return self.instr.query_str("CALC:FORM?")

    def set_power(self, power: float = -30):
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

    def get_data(self) -> list:
        resp = self.instr.query_bin_or_ascii_float_list("CALC:DATA? FDAT")
        real = resp[::2]
        imag = resp[1::2]
        return [r + i * 1j for r, i in zip(real, imag)]


if __name__ == "__main__":
    vna = VNABlock()
    print(vna.name())
    print(vna.set_start_frequency(2e9))
    print(vna.get_start_frequency())
    print(vna.set_stop_frequency(12e9))
    print(vna.get_stop_frequency())
    print(len(vna.get_data()))
