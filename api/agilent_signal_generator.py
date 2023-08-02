import logging

from settings import ADAPTERS
from state import state
from utils.classes import Singleton
from utils.functions import import_class


logger = logging.getLogger(__name__)


class AgilentSignalGenerator(metaclass=Singleton):
    ALC_RANGE = [-7.9, 2]
    ATTENUATOR_RANGE = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

    def __init__(
        self,
        host: str = state.AGILENT_SIGNAL_GENERATOR_IP,
        gpib: int = state.AGILENT_SIGNAL_GENERATOR_GPIB,
        adapter: str = "PROLOGIX_ETHERNET",
        *args,
        **kwargs,
    ):
        self.host = host
        self.gpib = gpib
        self.adapter_name = adapter
        self.adapter = None

        if self.adapter is None:
            self._set_adapter(adapter, *args, **kwargs)

    def _set_adapter(self, adapter: str, *args, **kwargs) -> None:
        adapter_path = ADAPTERS.get(adapter)
        try:
            adapter_class = import_class(adapter_path)
            self.adapter = adapter_class(host=self.host, *args, **kwargs)
        except (ImportError, ImportWarning) as e:
            logger.error(f"[{self.__class__.__name__}._set_adapter] {e}")

    def idn(self) -> str:
        logger.info(self.adapter)
        assert self.adapter is not None, "Adapter couldn't be None"
        return self.adapter.query("*IDN?", eq_addr=self.gpib)

    def test(self) -> str:
        assert self.adapter is not None, "Adapter couldn't be None"
        return self.adapter.query("*TST?", eq_addr=self.gpib)

    def reset(self) -> str:
        assert self.adapter is not None, "Adapter couldn't be None"
        return self.adapter.write("*RST", eq_addr=self.gpib)

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
        if value > 4:
            raise Exception("Value greater then 4 dBm unsupported!")
        k = int(round((abs(value) - 10) / 10))
        attenuation = self.ATTENUATOR_RANGE[k]
        alc = value + attenuation
        self.set_alc_level(0)
        self.set_attenuation_level(attenuation)
        self.set_alc_level(alc)


if __name__ == "__main__":
    dev = AgilentSignalGenerator(host="169.254.156.103", gpib=19)
    print("Power:")
    power = float(input())
    dev.set_amplitude(power)
