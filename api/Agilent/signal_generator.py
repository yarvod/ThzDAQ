import logging

import settings
from utils.classes import BaseInstrument


logger = logging.getLogger(__name__)


class SignalGenerator(BaseInstrument):
    model = "E8247C"
    ALC_RANGE = [-7.9, 2]
    ATTENUATOR_RANGE = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

    def __init__(
        self,
        host: str = "169.254.156.103",
        gpib: int = 19,
        adapter: str = settings.PROLOGIX_ETHERNET,
        port: int = 1234,
        *args,
        **kwargs,
    ):
        super().__init__(
            host=host, gpib=gpib, adapter=adapter, port=port, *args, **kwargs
        )

    def idn(self) -> str:
        return self.adapter.query("*IDN?", eq_addr=self.gpib)

    def test(self) -> bool:
        # return self.adapter.query("*TST?", eq_addr=self.gpib)
        result = self.idn()
        return "Agilent" in result

    def reset(self) -> str:
        assert self.adapter is not None, "Adapter couldn't be None"
        return self.adapter.write("*RST", eq_addr=self.gpib)

    def get_rf_output_state(self) -> bool:
        return bool(int(self.adapter.query("OUTPut?", eq_addr=self.gpib)))

    def set_rf_output_state(self, value: bool) -> None:
        output = 1 if value else 0
        self.adapter.write(f"OUTPut {output}", eq_addr=self.gpib)

    def get_frequency(self) -> float:
        return float(self.adapter.query(":FREQuency:FIXed? ", eq_addr=self.gpib))

    def set_frequency(self, value: float) -> None:
        self.adapter.write(f":FREQuency:FIXed {value} ", eq_addr=self.gpib)

    def get_attenuation_level(self) -> float:
        return float(self.adapter.query(":POWer:ATTenuation?", eq_addr=self.gpib))

    def set_attenuation_level(self, value: float) -> None:
        return self.adapter.write(f":POWer:ATTenuation {value}", eq_addr=self.gpib)

    def get_alc_level(self) -> float:
        return float(self.adapter.query(":POWer:ALC:LEVel?", eq_addr=self.gpib))

    def set_alc_level(self, value: float) -> None:
        return self.adapter.write(f":POWer:ALC:LEVel {value}", eq_addr=self.gpib)

    def get_amplitude(self) -> float:
        attenuation = self.get_attenuation_level()
        asc = self.get_alc_level()
        return asc - attenuation

    def set_amplitude(self, value: float) -> None:
        if value > 25:
            raise Exception("Value greater then 25 dBm unsupported!")
        k = int(round((abs(value) - 10) / 10))
        if k < 0 or value > 0:
            k = 0
        attenuation = self.ATTENUATOR_RANGE[k]
        alc = value + attenuation
        self.set_alc_level(0)
        self.set_attenuation_level(attenuation)
        self.set_alc_level(alc)

    def set_power(self, value: float) -> None:
        self.adapter.write(f"POW {value}dBm", eq_addr=self.gpib)

    def get_power(self) -> float:
        return float(self.adapter.query("POW?", eq_addr=self.gpib))

    def get_oem_status(self) -> str:
        """ON|OFF|NONE|REAR|FRONT"""
        return self.adapter.query(":SYSTem:OEMHead:SELect?", eq_addr=self.gpib)

    def set_oem_status(self, value: str) -> None:
        """ON|OFF|NONE|REAR|FRONT"""
        self.adapter.write(f":SYSTem:OEMHead:SELect {value}", eq_addr=self.gpib)

    def get_oem_frequency_start(self) -> float:
        return float(
            self.adapter.query(":SYSTem:OEMHead:FREQuency:STARt?", eq_addr=self.gpib)
        )

    def set_oem_frequency_start(self, value: float) -> None:
        self.adapter.write(
            f":SYSTem:OEMHead:FREQuency:STARt {value}", eq_addr=self.gpib
        )

    def get_oem_frequency_stop(self) -> float:
        return float(
            self.adapter.query(":SYSTem:OEMHead:FREQuency:STOP?", eq_addr=self.gpib)
        )

    def set_oem_frequency_stop(self, value: float) -> None:
        self.adapter.write(f":SYSTem:OEMHead:FREQuency:STOP {value}", eq_addr=self.gpib)

    def get_oem_multiplier(self) -> float:
        return float(self.adapter.query(":SYST:OEMH:FREQ:MULT?", eq_addr=self.gpib))

    def set_oem_multiplier(self, value: float) -> None:
        self.adapter.write(f":SYST:OEMH:FREQ:MULT {value}", eq_addr=self.gpib)


if __name__ == "__main__":
    dev = SignalGenerator(host="169.254.156.103", gpib=18)
    print(dev.idn())
    print(float(dev.adapter.query(f"POW?", eq_addr=dev.gpib)))
