import logging

from api.adapters.socket_adapter import SocketAdapter
from utils.classes import Singleton


logger = logging.getLogger(__name__)


class PrologixEthernetAdapter(SocketAdapter, metaclass=Singleton):
    socket = None
    host = None

    def __init__(
        self, host: str, port: int = 1234, timeout: float = 2, *args, **kwargs
    ):
        super().__init__(host, port, timeout, *args, **kwargs)
        self._setup()

    def _setup(self):
        # set device to CONTROLLER mode
        self._send("++mode 1")

        # disable read after write
        self._send("++auto 0")

        # set GPIB timeout
        self._send("++read_tmo_ms %i" % int(self.timeout * 1e3))

        # do not require CR or LF appended to GPIB data
        self._send("++eos 3")

    def select(self, eq_addr):
        self._send("++addr %i" % int(eq_addr))

    def write(self, cmd, eq_addr: int = None):
        if eq_addr:
            self.select(eq_addr)
        super().write(cmd)

    def read(self, eq_addr: int = None, num_bytes=1024):
        if eq_addr:
            self.select(eq_addr)
        self._send("++read eoi")
        return super().read(num_bytes)

    def query(self, cmd, eq_addr: int = None, buffer_size=1024 * 1024):
        if eq_addr:
            self.select(eq_addr)
        self.write(cmd)
        return self.read(num_bytes=buffer_size)


if __name__ == "__main__":
    print("IP address:")
    host = input()
    dev = PrologixEthernetAdapter(host=host)
    dev.connect()
    print("GPIB address:")
    gpib = int(input())
    dev.select(gpib)
    print(dev.query("*IDN?"))
