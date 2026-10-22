import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument, ScpiInstrument
from thzdaq_instruments.transport.base import HTTP, SERIAL, SOCKET, ConnectionSpec
from thzdaq_instruments.transport.http import JsonClient, JsonHttpClient
from thzdaq_instruments.units import PSI, celsius_to_kelvin

logger = logging.getLogger(__name__)

OPERATING_STATES = {
    0: "local off",
    1: "local on",
    2: "remote off",
    3: "remote on",
    4: "cold head run",
    5: "cold head pause",
    6: "fault off",
    7: "oil fault off",
}


def crc16_modbus(data: str) -> str:
    """Checksum of the F-70 protocol, 4 upper-case hex digits."""
    crc = 0xFFFF
    for byte in data.encode("ascii"):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return f"{crc:04X}"


@dataclass(frozen=True)
class F70Status:
    raw: int

    @property
    def system_on(self) -> bool:
        return bool(self.raw & 1 << 0)

    @property
    def alarms(self) -> Tuple[str, ...]:
        names = (
            (1, "motor temperature"),
            (2, "phase sequence/fuse"),
            (3, "helium temperature"),
            (4, "water temperature"),
            (5, "water flow"),
            (6, "oil level"),
            (7, "pressure"),
        )
        return tuple(name for bit, name in names if self.raw & 1 << bit)

    @property
    def solenoid_on(self) -> bool:
        return bool(self.raw & 1 << 8)

    @property
    def state(self) -> str:
        return OPERATING_STATES[(self.raw >> 9) & 0b111]

    @property
    def configuration(self) -> int:
        return 2 if self.raw & 1 << 15 else 1


class SumitomoF70(ScpiInstrument):
    """Sumitomo F-70 helium compressor, RS-232 protocol ($CMD + CRC + CR): Compressor.

    The legacy driver ended control commands with NUL instead of CR and read the
    status with the pressure command; both are fixed here.
    """

    @staticmethod
    def connection(
        serial_port: Optional[str] = None, host: Optional[str] = None, port: int = 23
    ) -> ConnectionSpec:
        """Direct serial port or a serial-to-Ethernet gateway."""
        common = dict(write_termination="\r", read_termination="\r", timeout=2.0)
        if host:
            return ConnectionSpec(SOCKET, host=host, port=port, **common)
        return ConnectionSpec(SERIAL, serial_port=serial_port, baudrate=9600, **common)

    def command(self, command: str) -> List[str]:
        """Send $CMD with checksum, return the reply fields without the command and CRC."""
        response = self.query(f"{command}{crc16_modbus(command)}")
        if response.startswith("$???"):
            raise InstrumentResponseError(f"{self.name}: {command!r} not understood")
        if not response.startswith(command):
            raise InstrumentResponseError(
                f"{self.name}: {command!r} answered {response!r}"
            )
        head, _, checksum = response.rpartition(",")
        if not head:
            # Echo only, e.g. "$ON177CF"
            body, checksum = response[:-4], response[-4:]
            if crc16_modbus(body) != checksum.upper():
                raise InstrumentResponseError(
                    f"{self.name}: bad checksum in {response!r}"
                )
            return []
        if checksum.upper() not in (crc16_modbus(head + ","), crc16_modbus(head)):
            raise InstrumentResponseError(f"{self.name}: bad checksum in {response!r}")
        return head.split(",")[1:]

    def _floats(self, command: str) -> List[float]:
        fields = self.command(command)
        try:
            return [float(v) for v in fields]
        except ValueError as e:
            raise InstrumentResponseError(f"{command} answered {fields!r}") from e

    def identify(self) -> str:
        # A serial port opens without the compressor: ask it something
        return f"Sumitomo F-70 {self.name}: {self.read_status().state}"

    def read_temperatures(self) -> List[float]:
        """Discharge, water out, water in, (spare), K"""
        return [celsius_to_kelvin(v) for v in self._floats("$TEA")]

    def read_pressures(self) -> List[float]:
        """Return pressure(s), Pa gauge"""
        return [v * PSI for v in self._floats("$PRA")]

    def read_status(self) -> F70Status:
        fields = self.command("$STA")
        try:
            return F70Status(int(fields[0], 16))
        except (IndexError, ValueError) as e:
            raise InstrumentResponseError(f"$STA answered {fields!r}") from e

    def turn_on(self) -> None:
        self.command("$ON1")

    def turn_off(self) -> None:
        self.command("$OFF")

    def reset(self) -> None:
        self.command("$RS1")

    def cold_head_run(self) -> None:
        self.command("$CHR")

    def cold_head_pause(self) -> None:
        self.command("$CHP")

    def cold_head_pause_off(self) -> None:
        self.command("$POF")


class SumitomoF70Rest(Instrument):
    """F-70 behind the lab REST service (°C and psig there): Compressor."""

    def __init__(
        self,
        connection: Optional[ConnectionSpec] = None,
        *,
        name: Optional[str] = None,
        client: Optional[JsonClient] = None,
    ):
        super().__init__(name=name)
        self.client = client or JsonHttpClient(connection or self.connection())

    @staticmethod
    def connection(host: str = "192.168.129.106", port: int = 21024) -> ConnectionSpec:
        return ConnectionSpec(HTTP, host=host, port=port, timeout=10.0)

    def identify(self) -> str:
        self.read_temperatures()  # the service answers or the request fails
        return f"Sumitomo F-70 REST {self.name}"

    def _values(self, path: str, key: str) -> List[float]:
        data = self.client.get(path)
        if data.get("error"):
            raise InstrumentResponseError(f"{self.name}: {data['error']}")
        try:
            return [float(v) for v in data[key]]
        except (KeyError, TypeError, ValueError) as e:
            raise InstrumentResponseError(
                f"{self.name}: {path} answered {data!r}"
            ) from e

    def read_temperatures(self) -> List[float]:
        return [
            celsius_to_kelvin(v)
            for v in self._values("/api/v1/temperatures/", "temperatures")
        ]

    def read_pressures(self) -> List[float]:
        return [v * PSI for v in self._values("/api/v1/pressures/", "pressures")]

    def turn_on(self) -> None:
        self.client.post("/api/v1/turn-on/")

    def turn_off(self) -> None:
        self.client.post("/api/v1/turn-off/")

    def close(self) -> None:
        self.client.close()
