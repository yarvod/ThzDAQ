from typing import Optional

from thzdaq_instruments.transport.base import Link, Transport


class PrologixController:
    """Prologix GPIB controller state on one link: setup once, current address."""

    def __init__(self, link: Link, timeout: float = 2.0):
        self.link = link
        self.timeout = timeout
        self._address: Optional[int] = None
        self._configured = False

    def setup(self) -> None:
        with self.link.lock:
            if self._configured:
                return
            self.link.write_line("++mode 1")  # controller mode
            self.link.write_line("++auto 0")  # no read-after-write, reads are explicit
            self.link.write_line(f"++read_tmo_ms {int(self.timeout * 1e3)}")
            self.link.write_line("++eos 3")  # don't append CR/LF to GPIB data
            self.link.write_line("++savecfg 0")
            self._configured = True

    def invalidate(self) -> None:
        """After a reconnect: set the controller up and select the address again."""
        with self.link.lock:
            self._configured = False
            self._address = None

    def select(self, address: int) -> None:
        with self.link.lock:
            self.setup()
            if self._address != address:
                self.link.write_line(f"++addr {int(address)}")
                self._address = address

    def read(self) -> str:
        self.link.write_line("++read eoi")
        return self.link.read_line()


class PrologixTransport(Transport):
    """GPIB instrument behind a Prologix controller shared with other instruments."""

    def __init__(
        self, link: Link, controller: PrologixController, address: int, **kwargs
    ):
        super().__init__(link, **kwargs)
        self.controller = controller
        self.address = address

    def _after_reset(self) -> None:
        self.controller.invalidate()

    def _write(self, command: str) -> None:
        self.controller.select(self.address)
        self.link.write_line(command)

    def _read(self) -> str:
        self.controller.select(self.address)
        return self.controller.read()
