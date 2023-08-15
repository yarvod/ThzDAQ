from state import state
from utils.classes import BaseInstrument


class TemperatureController(BaseInstrument):
    def __init__(
        self,
        host: str = state.LAKE_SHORE_IP,
        gpib: int = None,
        adapter: str = "SOCKET",
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self) -> str:
        if self.gpib:
            return self.adapter.query("*IDN?", eq_addr=self.gpib)
        return self.adapter.query("*IDN?")


if __name__ == "__main__":
    temp = TemperatureController(port=state.LAKE_SHORE_PORT)

    print(temp.idn())
