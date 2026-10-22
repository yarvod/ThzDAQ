from typing import Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.transport.base import HTTP, SERIAL, ConnectionSpec, Transport
from thzdaq_instruments.transport.http import JsonClient, JsonHttpClient
from thzdaq_instruments.transport.pool import TransportPool, default_pool


class ArduinoGrid(Instrument):
    """Wire grid polarizer on an Arduino stepper: Rotator.

    The HTTP firmware rotates by a relative angle, the serial one goes to an
    absolute angle; the driver keeps the current angle (no position readback).
    """

    def __init__(
        self,
        connection: Optional[ConnectionSpec] = None,
        *,
        name: Optional[str] = None,
        angle: float = 0.0,
        client: Optional[JsonClient] = None,
        transport: Optional[Transport] = None,
        pool: Optional[TransportPool] = None,
    ):
        super().__init__(name=name)
        connection = connection or self.connection()
        self.client = client
        self.transport = transport
        if client is None and transport is None:
            if connection.kind == HTTP:
                self.client = JsonHttpClient(connection)
            else:
                self.transport = (pool or default_pool).acquire(connection)
        self._angle = angle

    @staticmethod
    def connection(host: str = "169.254.0.52") -> ConnectionSpec:
        return ConnectionSpec(HTTP, host=host, timeout=30.0)

    @staticmethod
    def serial_connection(serial_port: str) -> ConnectionSpec:
        return ConnectionSpec(
            SERIAL, serial_port=serial_port, baudrate=9600, timeout=30.0
        )

    def identify(self) -> str:
        if not self.test():
            raise InstrumentResponseError(f"{self.name}: no OK to the test command")
        return f"Arduino grid {self.name}"

    def test(self) -> bool:
        if self.client is not None:
            self.client.post("/test", {})
            return True
        return self.transport.query("test") == "OK"

    def get_angle(self) -> float:
        return self._angle

    def set_angle_reference(self, angle: float) -> None:
        """Tell the driver where the grid is without moving it."""
        self._angle = angle

    def rotate_to(self, angle: float) -> float:
        if self.client is not None:
            response = self.client.post("/rotate", {"angle": angle - self._angle})
            if response.get("error"):
                raise InstrumentResponseError(f"{self.name}: {response['error']}")
        else:
            self.transport.write(f"{angle}")
        self._angle = angle
        return angle

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.transport is not None:
            self.transport.close()
