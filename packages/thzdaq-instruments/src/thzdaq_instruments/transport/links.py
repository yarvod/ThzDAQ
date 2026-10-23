import socket
import sys
from typing import Optional

from thzdaq_instruments.errors import (
    InstrumentConnectionError,
    InstrumentTimeoutError,
)
from thzdaq_instruments.transport.base import Link

CHUNK_SIZE = 4096


class SocketLink(Link):
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 2.0,
        write_termination: str = "\n",
        read_termination: Optional[str] = "\n",
        encoding: str = "ascii",
    ):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.write_termination = write_termination
        self.read_termination = read_termination
        self.encoding = encoding
        self._socket: Optional[socket.socket] = None
        self._buffer = b""

    def __repr__(self):
        return f"SocketLink({self.host}:{self.port})"

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def open(self) -> None:
        if self._socket is not None:
            return
        try:
            self._socket = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
        except OSError as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e
        self._socket.settimeout(self.timeout)
        self._buffer = b""

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.close()
        finally:
            self._socket = None
            self._buffer = b""

    def _abort(self) -> None:
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)  # wakes a blocked recv() on POSIX
            except OSError:
                pass
            if sys.platform == "win32":
                # Windows keeps recv() waiting after shutdown; closesocket() ends
                # it with an error. The next use reconnects (the link is broken).
                try:
                    sock.close()
                except OSError:
                    pass

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise InstrumentConnectionError(f"{self!r} is not open")
        return self._socket

    def write_line(self, line: str) -> None:
        data = (line + self.write_termination).encode(self.encoding)
        try:
            self._require_socket().sendall(data)
        except socket.timeout as e:
            raise InstrumentTimeoutError(f"{self!r}: write timeout") from e
        except OSError as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e

    def _recv(self) -> bytes:
        try:
            chunk = self._require_socket().recv(CHUNK_SIZE)
        except socket.timeout as e:
            raise InstrumentTimeoutError(f"{self!r}: read timeout") from e
        except OSError as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e
        if not chunk:
            raise InstrumentConnectionError(f"{self!r}: connection closed by peer")
        return chunk

    def read_line(self) -> str:
        if self.read_termination is None:
            return self._recv().decode(self.encoding).rstrip("\r\n")
        terminator = self.read_termination.encode(self.encoding)
        while terminator not in self._buffer:
            self._buffer += self._recv()
        line, self._buffer = self._buffer.split(terminator, 1)
        return line.decode(self.encoding).rstrip("\r")


class SerialLink(Link):
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 2.0,
        write_termination: str = "\n",
        read_termination: Optional[str] = "\n",
        encoding: str = "ascii",
    ):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_termination = write_termination
        self.read_termination = read_termination
        self.encoding = encoding
        self._serial = None

    def __repr__(self):
        return f"SerialLink({self.port})"

    @property
    def is_open(self) -> bool:
        return self._serial is not None

    def open(self) -> None:
        if self._serial is not None:
            return
        import serial

        try:
            self._serial = serial.Serial(
                port=self.port, baudrate=self.baudrate, timeout=self.timeout
            )
        except (serial.SerialException, OSError) as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
        finally:
            self._serial = None

    def _abort(self) -> None:
        port = self._serial
        if port is not None:
            try:
                port.cancel_read()
            except (AttributeError, OSError):
                pass

    def _require_serial(self):
        if self._serial is None:
            raise InstrumentConnectionError(f"{self!r} is not open")
        return self._serial

    def write_line(self, line: str) -> None:
        data = (line + self.write_termination).encode(self.encoding)
        try:
            self._require_serial().write(data)
        except OSError as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e

    def read_line(self) -> str:
        port = self._require_serial()
        try:
            if self.read_termination is None:
                data = port.read(CHUNK_SIZE)
                terminated = bool(data)
            else:
                terminator = self.read_termination.encode(self.encoding)
                data = port.read_until(terminator)
                terminated = data.endswith(terminator)
        except OSError as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e
        if not terminated:
            raise InstrumentTimeoutError(f"{self!r}: read timeout")
        return data.decode(self.encoding).rstrip("\r\n\x00")


class VisaLink(Link):
    """Any VISA resource through pyvisa (install the `visa` extra and a VISA backend).

    Covers GPIB adapters other than Prologix (NI GPIB-USB-HS, Keysight 82357B),
    USBTMC and LXI instruments. VISA addresses the bus itself, so each resource
    is its own link.
    """

    def __init__(
        self,
        resource: str,
        timeout: float = 2.0,
        write_termination: str = "\n",
        read_termination: Optional[str] = "\n",
        backend: str = "",
    ):
        super().__init__()
        self.resource = resource
        self.timeout = timeout
        self.write_termination = write_termination
        self.read_termination = read_termination
        self.backend = backend
        self._instrument = None

    def __repr__(self):
        return f"VisaLink({self.resource})"

    @property
    def is_open(self) -> bool:
        return self._instrument is not None

    def _errors(self):
        import pyvisa

        return pyvisa.errors.VisaIOError, pyvisa.constants.StatusCode.error_timeout

    def open(self) -> None:
        if self._instrument is not None:
            return
        try:
            import pyvisa
        except ImportError as e:
            raise InstrumentConnectionError(
                "pyvisa is not installed: add the thzdaq-instruments[visa] extra"
            ) from e
        try:
            manager = pyvisa.ResourceManager(self.backend)
            instrument = manager.open_resource(self.resource)
        except (pyvisa.errors.VisaIOError, OSError, ValueError) as e:
            raise InstrumentConnectionError(f"{self!r}: {e}") from e
        instrument.timeout = int(self.timeout * 1e3)
        instrument.write_termination = self.write_termination
        instrument.read_termination = self.read_termination
        self._instrument = instrument

    def close(self) -> None:
        if self._instrument is None:
            return
        try:
            self._instrument.close()
        finally:
            self._instrument = None

    def _require(self):
        if self._instrument is None:
            raise InstrumentConnectionError(f"{self!r} is not open")
        return self._instrument

    def _call(self, func, *args):
        visa_error, timeout_code = self._errors()
        try:
            return func(*args)
        except visa_error as e:
            if getattr(e, "error_code", None) == timeout_code:
                raise InstrumentTimeoutError(f"{self!r}: timeout") from e
            raise InstrumentConnectionError(f"{self!r}: {e}") from e

    def write_line(self, line: str) -> None:
        self._call(self._require().write, line)

    def read_line(self) -> str:
        return self._call(self._require().read).rstrip("\r\n")
