"""Pfeiffer Vacuum telegram protocol (TC 110 drive, HiCube, gauges) over RS-485.

Telegram: AAA AC PPP LL DATA CCC CR — address, action (00 read, 10 write/answer),
parameter, data length, data, checksum = sum of the preceding bytes mod 256.
"""

import math
from typing import Any, Optional, Union

from thzdaq_instruments.drivers.pfeiffer_parameters import (
    BY_NAME,
    PARAMETERS,
    Parameter,
)
from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.transport.base import SERIAL, SOCKET, ConnectionSpec, Transport
from thzdaq_instruments.units import HPA, celsius_to_kelvin

BOOLEAN_OLD, U_INTEGER, U_REAL, U_EXPO, STRING = 0, 1, 2, 3, 4
BOOLEAN_NEW, U_SHORT_INT, U_EXPO_NEW, STRING16, STRING8 = 6, 7, 10, 11, 12
DEVICE_ERRORS = {
    "NO_DEF": "undefined parameter",
    "_RANGE": "value out of range",
    "_LOGIC": "logic access violation",
}


def checksum(text: str) -> str:
    return f"{sum(text.encode('ascii')) % 256:03d}"


def decode(data_type: int, raw: str) -> Any:
    """Device string -> Python value."""
    try:
        if data_type == BOOLEAN_OLD:
            return {"000000": False, "111111": True}[raw]
        if data_type == BOOLEAN_NEW:
            return {"0": False, "1": True}[raw]
        if data_type in (U_INTEGER, U_SHORT_INT):
            return int(raw)
        if data_type == U_REAL:
            # Fixed point with two decimals: "001571" = 15.71
            return int(raw) / 100
        if data_type == U_EXPO_NEW:
            # Mantissa with three decimals, exponent offset by 20: "100023" = 1.000e3
            return int(raw[:4]) / 1000 * 10 ** (int(raw[4:]) - 20)
        if data_type == U_EXPO:
            return float(raw)
        return raw
    except (KeyError, ValueError) as e:
        raise InstrumentResponseError(
            f"Can't decode {raw!r} as type {data_type}"
        ) from e


def encode(data_type: int, value: Any) -> str:
    """Python value -> device string."""
    if data_type == BOOLEAN_OLD:
        return "111111" if value else "000000"
    if data_type == BOOLEAN_NEW:
        return "1" if value else "0"
    if data_type == U_INTEGER:
        return f"{int(value):06d}"
    if data_type == U_SHORT_INT:
        return f"{int(value):03d}"
    if data_type == U_REAL:
        return f"{round(value * 100):06d}"
    if data_type == U_EXPO_NEW:
        if value <= 0:
            return "000000"
        exponent = math.floor(math.log10(value))
        mantissa = round(value / 10**exponent * 1000)
        if mantissa >= 10000:
            mantissa, exponent = 1000, exponent + 1
        return f"{mantissa:04d}{exponent + 20:02d}"
    if data_type == STRING:
        return f"{value:<6}"[:6]
    if data_type == STRING16:
        return f"{value:<16}"[:16]
    if data_type == STRING8:
        return f"{value:<8}"[:8]
    raise ConfigurationError(f"Writing data type {data_type} is not supported")


def read_telegram(address: int, parameter: int) -> str:
    body = f"{address:03d}00{parameter:03d}02=?"
    return body + checksum(body)


def write_telegram(address: int, parameter: int, data: str) -> str:
    body = f"{address:03d}10{parameter:03d}{len(data):02d}{data}"
    return body + checksum(body)


def parse_telegram(response: str, address: int, parameter: int) -> str:
    """Validate an answer and return its data field."""
    if len(response) < 13 or checksum(response[:-3]) != response[-3:]:
        raise InstrumentResponseError(f"Bad Pfeiffer telegram {response!r}")
    if int(response[:3]) != address or int(response[5:8]) != parameter:
        raise InstrumentResponseError(
            f"Answer {response!r} is not for {address:03d}/{parameter:03d}"
        )
    length = int(response[8:10])
    data = response[10:-3]
    if len(data) != length:
        raise InstrumentResponseError(f"Data length mismatch in {response!r}")
    if data in DEVICE_ERRORS:
        raise InstrumentResponseError(
            f"Parameter {parameter:03d}: {DEVICE_ERRORS[data]}"
        )
    return data


ParameterRef = Union[int, str]


class PfeifferDevice(ScpiInstrument):
    """One device on the Pfeiffer RS-485 bus; several share a link through the pool."""

    def __init__(
        self, transport: Transport, *, name: Optional[str] = None, address: int = 1
    ):
        super().__init__(transport, name=name)
        if not 1 <= address <= 255:
            raise ConfigurationError(f"RS-485 address {address} is out of 1..255")
        self.address = address

    @staticmethod
    def connection(
        serial_port: Optional[str] = None, host: Optional[str] = None, port: int = 4001
    ) -> ConnectionSpec:
        """USB/RS-485 adapter or an RS-485 to Ethernet gateway."""
        common = dict(write_termination="\r", read_termination="\r", timeout=2.0)
        if host:
            return ConnectionSpec(SOCKET, host=host, port=port, **common)
        return ConnectionSpec(SERIAL, serial_port=serial_port, baudrate=9600, **common)

    @staticmethod
    def parameter(ref: ParameterRef) -> Parameter:
        found = BY_NAME.get(ref) if isinstance(ref, str) else PARAMETERS.get(ref)
        if found is None:
            raise ConfigurationError(f"Unknown Pfeiffer parameter {ref!r}")
        return found

    def read_raw(self, number: int) -> str:
        response = self.query(read_telegram(self.address, number))
        return parse_telegram(response, self.address, number)

    def write_raw(self, number: int, data: str) -> str:
        response = self.query(write_telegram(self.address, number, data))
        return parse_telegram(response, self.address, number)

    def get_parameter(self, ref: ParameterRef) -> Any:
        parameter = self.parameter(ref)
        if "R" not in parameter.access:
            raise ConfigurationError(f"{parameter.name} is write-only")
        return decode(parameter.data_type, self.read_raw(parameter.number))

    def set_parameter(self, ref: ParameterRef, value: Any) -> None:
        parameter = self.parameter(ref)
        if "W" not in parameter.access:
            raise ConfigurationError(f"{parameter.name} is read-only")
        data = encode(parameter.data_type, value)
        if self.write_raw(parameter.number, data) != data:
            raise InstrumentResponseError(f"{parameter.name}: write not acknowledged")

    def identify(self) -> str:
        return f"Pfeiffer {self.get_parameter('ElecName').strip()} @{self.address:03d}"

    def error_code(self) -> str:
        """'000000' when there is no error"""
        return self.get_parameter("Error_code")


class PfeifferTurboPump(PfeifferDevice):
    """TC 110 drive of a HiPace/HiCube turbo pump."""

    def set_pumping_station(self, value: bool) -> None:
        self.set_parameter("PumpgStatn", value)

    def get_pumping_station(self) -> bool:
        return self.get_parameter("PumpgStatn")

    def set_motor(self, value: bool) -> None:
        self.set_parameter("MotorPump", value)

    def acknowledge_error(self) -> None:
        self.set_parameter("ErrorAckn", True)

    def actual_speed(self) -> float:
        """Hz"""
        return float(self.get_parameter("ActualSpd"))

    def nominal_speed(self) -> float:
        """Hz"""
        return float(self.get_parameter("Nominal_Spd"))

    def drive_current(self) -> float:
        """A"""
        return self.get_parameter("DrvCurrent")

    def drive_power(self) -> float:
        """W"""
        return float(self.get_parameter("DrvPower"))

    def temperatures(self) -> dict:
        """K: electronics, pump bottom, bearing, motor"""
        return {
            key: celsius_to_kelvin(self.get_parameter(name))
            for key, name in (
                ("electronics", "TempElec"),
                ("pump_bottom", "TempPmpBot"),
                ("bearing", "TempBearng"),
                ("motor", "TempMotor"),
            )
        }

    def read_pressure(self) -> float:
        """Pa, from the gauge connected to the drive"""
        return self.get_parameter("Pressure") * HPA


class PfeifferGauge(PfeifferDevice):
    """Active gauge on the bus (TPR, PKR, ...): VacuumGauge."""

    def read_pressure(self) -> float:
        """Pa"""
        return self.get_parameter(740) * HPA
