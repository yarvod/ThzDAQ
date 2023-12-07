from typing import Literal

from settings import SOCKET
from utils.classes import BaseInstrument
from utils.decorators import exception


class NRXPowerMeter(BaseInstrument):
    def __init__(
        self,
        host: str = "169.254.2.20",
        gpib: int = None,
        adapter: str = SOCKET,
        port: int = 5025,
        aperture_time: float = 0.05,
        filter_time: float = 100,
        *args,
        **kwargs,
    ):
        """
        :param host:
        :param gpib:
        :param adapter:
        :param port:
        :param aperture_time: ms
        :param filter_time: s
        :param args:
        :param kwargs:
        """
        kwargs["port"] = port
        super().__init__(host, gpib, adapter, *args, **kwargs)
        # self.set_filter_time(filter_time)
        self.set_filter_state(0)
        self.set_aperture_time(aperture_time)

    @exception
    def reset(self):
        self.write("*RST")

    def configure(self):
        self.write("CONF1 -50,3,(@1)")

    @exception
    def idn(self):
        """Method to get power meter name"""
        return self.query("*IDN?")

    @exception
    def test(self):
        """Method to test power meter"""
        return self.query("*TST?")

    @exception
    def get_power(self):
        """Main method to get power from power meter"""
        return float(self.query("READ?"))

    @exception
    def get_conf(self):
        """Get current power meter config"""
        return self.query("CONF?")

    @exception
    def fetch(self):
        """Get data without new measure, it will return old measured value"""
        return float(self.query("FETCH?"))

    @exception
    def set_lower_limit(self, limit: float):
        """Set lower measurement limit"""
        self.write(f"CALCulate1:LIMit1:LOWer:DATA {limit}")

    @exception
    def set_upper_limit(self, limit: float):
        """Set upper measurement limit"""
        self.write(f"CALCulate1:LIMit1:UPPer:DATA {limit}")

    @exception
    def set_filter_state(self, value: int = 0):
        """Filter state: On - 1, Off - 0"""
        self.write(f"CALC:CHAN:AVER:STAT {value}")

    @exception
    def set_filter_time(self, time: float = 0.05):
        """
        Setting filter time
        :param time: seconds
        :return:
        """
        self.write(f"CALCulate:CHANnel:AVERage:COUNt:AUTO:MTIMe {time}")

    @exception
    def set_aperture_time(self, time: float = 50):
        """
        Setting averaging time
        :param time: seconds
        :return:
        """
        self.write(f"CALC:APER {time / 1e3}")

    def set_power_units(self, value=Literal["DBM", "DBUV", "W"]):
        self.write(f"UNIT1:POWer {value}")

    def get_power_units(self):
        return self.query("UNIT1:POWer?")


if __name__ == "__main__":
    nrx = NRXPowerMeter(delay=0)
    nrx.write(f"CALC:APER 0.2")
