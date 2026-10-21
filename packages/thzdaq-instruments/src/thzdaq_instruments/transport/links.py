import socket
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
