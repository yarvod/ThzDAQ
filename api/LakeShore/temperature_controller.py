from api.adapters.socket_adapter import SocketAdapter
from settings import SOCKET
from store.state import state
from utils.classes import BaseInstrument


class TemperatureController(BaseInstrument):
    def __init__(
        self,
        host: str = state.LAKE_SHORE_IP,
        gpib: int = None,
        adapter: str = SOCKET,
        *args,
        **kwargs,
    ):
        self.adapter = SocketAdapter(host=host, port=kwargs.get("port"))
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self) -> str:
        return self.query("*IDN?")

    def test(self) -> str:
        result = self.idn()
        if "LSCI,MODEL336,LSA2CMQ/LSA2C8R,2.9" in result:
            return "OK"
        return "ERROR"

    def get_temperature_a(self) -> float:
        return float(self.query("KRDG? A"))

    def get_temperature_c(self) -> float:
        return float(self.query("KRDG? C"))


if __name__ == "__main__":
    tc = TemperatureController(port=state.LAKE_SHORE_PORT)
    print(tc.idn())
    print(tc.get_temperature_a())
    print(tc.get_temperature_c())
