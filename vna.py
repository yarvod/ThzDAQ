from config import VNA_ADDRESS, VNA_SPARAM, VNA_POINTS

from RsInstrument import *

from utils import Singleton


class Instrument(RsInstrument, metaclass=Singleton):
    ...


class VNABlock:
    def __init__(self, vna_ip: str = VNA_ADDRESS, param: str = VNA_SPARAM):
        self.vna_ip = vna_ip
        self.param = param

    @property
    def instr(self):
        return Instrument(f'TCPIP::{VNA_ADDRESS}::INSTR', id_query=True, reset=True)

    def name(self):
        return self.instr.query_str("*IDN?")

    def test(self) -> str:
        """
        Methods for self testing Instrument.
        Error - 1
        Ok - 0
        """
        return self.instr.query_str("*TST?")

    def create_trace(self, points: int = VNA_POINTS):
        self.instr.write_int("SWE:POIN", points)

    def get_start_frequency(self):
        return self.instr.query_str("SENS:FREQ:STAR?")

    def get_stop_frequency(self):
        return self.instr.query_str("SENS:FREQ:STOP?")

    def set_start_frequency(self, freq: float):
        self.instr.write_float("SENS:FREQ:STAR", freq)

    def set_stop_frequency(self, freq: float):
        self.instr.write_float("SENS:FREQ:STOP", freq)

    def get_data(self):
        return self.instr.query_str("CALC1:PAR:SDEF 'Ch1Tr1', 'S21'")



if __name__ == "__main__":
    vna = VNABlock()
    print(vna.name())
    print(vna.test())
    print(vna.create_trace())
    print(vna.set_start_frequency(2e9))
    print(vna.get_start_frequency())
    print(vna.set_stop_frequency(12e9))
    print(vna.get_stop_frequency())
    print(vna.get_data())
