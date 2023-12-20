from api.adapters.socket_adapter import SocketAdapter


class Prologix(SocketAdapter):
    def __init__(
        self,
        host: str,
        port: int = 1234,
        timeout: float = 2,
        delay: float = 0,
        *args,
        **kwargs,
    ):
        super().__init__(host, port, timeout, delay, *args, **kwargs)
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

        self._send("++savecfg 0")

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
        self.write(cmd, eq_addr)
        return self.read(eq_addr, buffer_size)


if __name__ == "__main__":
    p = Prologix("169.254.156.103", 1234)
    print(p.query("*IDN?", eq_addr=20))
