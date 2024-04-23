import settings
from utils.classes import BaseInstrument


class LockIn(BaseInstrument):
    def __init__(
        self,
        host: str = "",
        gpib: int = 8,
        adapter: str = settings.PROLOGIX_ETHERNET,
        port: int = None,
        *args,
        **kwargs,
    ):
        kwargs["port"] = port
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")

    def get_out3(self):
        return float(self.query("OUTP? 3"))


if __name__ == "__main__":
    lockin = LockIn()
    print(lockin.idn())
    print(lockin.get_out3())
