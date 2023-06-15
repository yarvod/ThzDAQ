from RsInstrument import *

from config import config
from utils.classes import BaseInstrumentInterface
from utils.decorators import exception
from utils.logger import logger


class NRXBlock(BaseInstrumentInterface):
    def __init__(
        self,
        ip: str = config.NRX_IP,
        aperture_time: float = config.NRX_APER_TIME,
        filter_time: float = config.NRX_FILTER_TIME,
    ):
        self.address = f"TCPIP::{ip}::INSTR"
        self.instr = None

        self.connect()
        # self.set_filter_time(filter_time)
        self.set_filter_state(0)
        self.set_aperture_time(aperture_time)

    @exception
    def connect(self):
        self.instr = RsInstrument(self.address, reset=False)

    @exception
    def disconnect(self):
        self.instr.close()
        logger.info(f"[NRXBlock.close] NRX block closed")

    @exception
    def reset(self):
        self.instr.write("*RST")

    def configure(self):
        self.instr.write("CONF1 -50,3,(@1)")

    @exception
    def idn(self):
        """Method to get power meter name"""
        return self.instr.query("*IDN?")

    @exception
    def test(self):
        """Method to test power meter"""
        return self.instr.query("*TST?")

    @exception
    def get_power(self):
        """Main method to get power from power meter"""
        return self.instr.query_float("READ?")

    @exception
    def get_conf(self):
        """Get current power meter config"""
        return self.instr.query("CONF?")

    @exception
    def fetch(self):
        """Get data without new measure, it will return old measured value"""
        return self.instr.query_float("FETCH?")

    @exception
    def set_lower_limit(self, limit: float):
        """Set lower measurement limit"""
        self.instr.write(f"CALCulate1:LIMit1:LOWer:DATA {limit}")

    @exception
    def set_upper_limit(self, limit: float):
        """Set upper measurement limit"""
        self.instr.write(f"CALCulate1:LIMit1:UPPer:DATA {limit}")

    @exception
    def set_filter_state(self, state: int = 0):
        """Filter state: On - 1, Off - 0"""
        self.instr.write(f"CALC:CHAN:AVER:STAT {state}")

    @exception
    def set_filter_time(self, time: float = config.NRX_FILTER_TIME):
        """
        Setting filter time
        :param time: seconds
        :return:
        """
        self.instr.write(f"CALCulate:CHANnel:AVERage:COUNt:AUTO:MTIMe {time}")

    @exception
    def set_aperture_time(self, time: float = config.NRX_APER_TIME):
        """
        Setting averaging time
        :param time: seconds
        :return:
        """
        self.instr.write(f"CALC:APER {time}")

    def __del__(self):
        self.disconnect()
        logger.info(f"[NRXBlock.__del__] Instance {self} deleted")


if __name__ == "__main__":
    nrx = NRXBlock()
    nrx.instr.write(f"CALC:APER 0.2")
