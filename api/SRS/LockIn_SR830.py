import settings
from store.state import state
from utils.classes import BaseInstrument


class LockIn(BaseInstrument):
    def __init__(
        self,
        host: str = state.PROLOGIX_IP,
        gpib: int = None,
        adapter: str = settings.PROLOGIX_ETHERNET,
        port: int = state.VNA_PORT,
        *args,
        **kwargs,
    ):
        kwargs["port"] = port
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")


if __name__ == "__main__":
    lockin = LockIn()
    lockin.adapter.scan_gpib()
    # print(lockin.idn())
