import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Callable, Iterator, Optional

from thzdaq_instruments.errors import ConfigurationError, InstrumentConnectionError

SOCKET = "socket"
SERIAL = "serial"
PROLOGIX = "prologix"  # Prologix GPIB-Ethernet
PROLOGIX_USB = "prologix_usb"
KINDS = (SOCKET, SERIAL, PROLOGIX, PROLOGIX_USB)

PROLOGIX_DEFAULT_PORT = 1234


@dataclass(frozen=True)
class ConnectionSpec:
    """Where and how an instrument is connected."""

    kind: str
    host: Optional[str] = None
    port: Optional[int] = None
    serial_port: Optional[str] = None
    gpib: Optional[int] = None
    timeout: float = 2.0  # s
    read_delay: float = 0.0  # s, pause between write and read in query()
    baudrate: int = 9600
    write_termination: str = "\n"
    # None - legacy mode: one chunk per read, for devices without a terminator
    read_termination: Optional[str] = "\n"

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ConfigurationError(f"Unknown connection kind {self.kind!r}")
        if self.kind in (SOCKET, PROLOGIX):
            if not self.host:
                raise ConfigurationError(f"{self.kind} connection requires host")
            if self.port is None:
                if self.kind == SOCKET:
                    raise ConfigurationError("socket connection requires port")
                object.__setattr__(self, "port", PROLOGIX_DEFAULT_PORT)
        if self.kind in (SERIAL, PROLOGIX_USB) and not self.serial_port:
            raise ConfigurationError(f"{self.kind} connection requires serial_port")
        if self.is_prologix and (self.gpib is None or not 0 <= self.gpib <= 30):
            raise ConfigurationError("Prologix connection requires GPIB address 0..30")
        if self.timeout <= 0:
            raise ConfigurationError("timeout must be positive")

    @property
    def is_prologix(self) -> bool:
        return self.kind in (PROLOGIX, PROLOGIX_USB)

    @property
    def link_key(self) -> tuple:
        """Identifies the physical connection shared by instruments."""
        if self.kind in (SOCKET, PROLOGIX):
            return ("tcp", self.host, int(self.port))
        return ("serial", self.serial_port)

    def with_gpib(self, gpib: int) -> "ConnectionSpec":
        return replace(self, gpib=gpib)


class Link(ABC):
    """Physical line-oriented connection (TCP socket, serial port)."""

    def __init__(self):
        # Reentrant: a transport holds it for a whole query or transaction
        self.lock = threading.RLock()

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...

    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def write_line(self, line: str) -> None:
        ...

    @abstractmethod
    def read_line(self) -> str:
        ...


class Transport(ABC):
    """Command level access to one instrument over a (possibly shared) link.

    Every write/read/query holds the link lock, so instruments sharing a link
    (e.g. several GPIB devices behind one Prologix) never interleave commands.
    """

    def __init__(
        self,
        link: Link,
        read_delay: float = 0.0,
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.link = link
        self.read_delay = read_delay
        self._on_close = on_close
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self):
        if self._closed:
            raise InstrumentConnectionError("Transport is closed")

    def write(self, command: str) -> None:
        with self.link.lock:
            self._check_open()
            self._write(command)

    def read(self) -> str:
        with self.link.lock:
            self._check_open()
            return self._read()

    def query(self, command: str) -> str:
        with self.link.lock:
            self._check_open()
            self._write(command)
            if self.read_delay:
                time.sleep(self.read_delay)
            return self._read()

    @contextmanager
    def transaction(self) -> Iterator["Transport"]:
        """Keep the link for several commands that must not be interleaved."""
        with self.link.lock:
            self._check_open()
            yield self

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._on_close is not None:
            self._on_close()

    @abstractmethod
    def _write(self, command: str) -> None:
        ...

    @abstractmethod
    def _read(self) -> str:
        ...


class MessageTransport(Transport):
    """Instrument talking directly over the link."""

    def _write(self, command: str) -> None:
        self.link.write_line(command)

    def _read(self) -> str:
        return self.link.read_line()
