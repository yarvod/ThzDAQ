from typing import Any, Mapping, Optional

from thzdaq_instruments.angle import CountedAngle
from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.transport.base import HTTP, SERIAL, ConnectionSpec, Transport
from thzdaq_instruments.transport.http import JsonClient, JsonHttpClient
from thzdaq_instruments.state import State
from thzdaq_instruments.transport.pool import TransportPool, default_pool

ORIGIN = "origin"  # the serial firmware's own angle at the program's 0°


class ArduinoGrid(CountedAngle, Instrument):
    """Wire grid polarizer on an Arduino stepper: Rotator, KeptState.

    The HTTP firmware rotates by a relative angle, the serial one goes to an
    absolute angle of its own count; the driver counts the current angle (no
    position readback, thzdaq_instruments.angle). Its zero is the program's:
    over serial the driver keeps the firmware's angle at it (origin).
    """

    driver_key = "arduino.grid"
    device_type = "grid"

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
        self._origin = 0.0

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

    @property
    def unknown(self) -> str:
        if self.client is not None:
            return super().unknown
        return "angle unknown, a move did not end: rotate it to an angle"

    def set_angle_reference(self, angle: float) -> None:
        if self.client is None:
            # The firmware's angle where it stands stays: the origin moves
            self._origin += self.get_angle() - angle
        super().set_angle_reference(angle)

    def _move(self, angle: float) -> None:
        if self.client is None:
            self.transport.write(f"{angle + self._origin}")
            return
        response = self.client.post("/rotate", {"angle": angle - self.get_angle()})
        if response.get("error"):
            raise InstrumentResponseError(f"{self.name}: {response['error']}")

    def kept_state(self) -> State:
        return {**super().kept_state(), ORIGIN: self._origin}

    def restore_state(self, state: Mapping[str, Any]) -> None:
        super().restore_state(state)
        self._origin = float(state.get(ORIGIN, 0.0))

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.transport is not None:
            self.transport.close()
